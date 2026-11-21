# Final whole-branch review: compute-dispatch hoist (778ab5f9..fbb55b56)

Reviewer: final whole-branch seat (read-only; no subagents). Inputs: review package diff, spec, plan (Global Constraints,
Review Focus), ledger (R1-R17 and deferred minors), and the worktree source around every call site the hoist touches
(`draw_inner`, `dispatch()`, `encode_args`, `state_op`, `fz_next`, `mtl_exec_list`, usnap / renamed-update code,
`disp_enc` / `nvn_dispatch_order.h`, `lay_*`, `frz_op` / `rt_op`, `totk_vpool.c`, `hle_nvn.c` submit path).
I did one pass over the diff and a second pass over the side effects of the `dispatch()` that `csh_try` calls.

## Strengths

- **The moved list lasts one submission only.** `csh_try` resets the list when `g_csh.sub != g_sub_serial`
  (nvn_cs_hoist.inc:197), and so does `csh_take` (nvn_cs_hoist.inc:54). `g_sub_serial` advances only in `mtl_sub_begin`
  (nvn_mtl.m:1791). Mid-submission chunk commits (`chunk_maybe_split` in `rp_begin_ex`) do not advance it, so a chunk
  commit cannot strand a moved pointer. Probe scenario G guards this.
- **A dispatch is not moved twice.** The "already run ahead" check (nvn_cs_hoist.inc:222-223) stops a rescan at a pointer
  that is still on the list. That covers the draw that does not open the pass (scenarios H and I). It also covers the same
  sub-list called twice in one submission, where both instances share one op pointer: the second instance is never moved,
  and the replay removes the first one at its own place.
- **State is restored the same way the tested scans restore it** (`shader_predict_rest`, `geo_run`). The scan copies and
  restores `S` and `R`, calls `args_dirty_all()`, and sets `g_pso_dirty |= moved` and `g_dss_dirty |= moved`
  (nvn_cs_hoist.inc:206, 238). Side effects of `state_op` that are not restored are harmless:
  - `TEX_CHANGED` takes a fresh, never-reused `g_tex_gen_seq`, so a restored `tex_gen` can never match a cache keyed on it.
  - `args_program_changed` and the argument epochs only invalidate more.
  - `g_prog_for_draw` is 0 outside its own local set and reset, so `csh_try` does not need to save it.
- **The hook sits at the right place.** It comes after every early return of `draw_inner` (empty scissor, `cg_take`,
  render disabled, defer `in_p`) and before `rp_begin_ex` (nvn_mtl.m:19392). The only exit between the hook and the pass
  opening is `!en`, and the rescan check covers it.
- **Entry refusals match the Global Constraints, plus a conservative `g_defer_nact` (R4).** `g_defer_natq > 0` implies
  `g_defer_nact > 0`, so a deferred P replayed into Q's pass is never crossed. Stop ops are tested before `state_op`
  (R2). `fz_next` stops at event waits and at a bad cursor. The `g_ret_n > 8` refusal matches the 8-slot cursor stack.
- **The pre-scan matches the full scan.** `csh_ahead` lists exactly the ops `state_op` takes, minus `RENDER_COND` and
  `RENDER_ENABLE`. A pass with no dispatch ahead costs only op-code reads.
- **The dependency rules are general and conservative.**
  - Every unknown binding kind falls through to "stop" or "refuse".
  - The draw rules judge the shader variant the draw will actually use (`stage_sig`, then `alt`; scenario U).
  - Attachment storage is compared by canonical storage (`csh_attachment_hit`, `csh_tex_alias`). An unknown size is
    treated as an alias.
- **The virtual-pool view is sound.**
  - Writers change the table only under `g_map_mu` (`vmap_note` is called inside `apply_request`, which runs under
    `totk_vpool_map`'s lock, as do init and fini).
  - `totk_vpool_view_sync` copies the table under the same lock, and only when the generation counter changed.
  - `totk_vpool_canon` refuses ranges that cross a pool border, touch a hole, cross non-contiguous backing, or arrive
    after an overflow.
  - I traced `vmap_cut` by hand: split, tail trim, head trim and removal all keep the table sorted and disjoint.
  - A stale mapping to a freed physical pool can only over-report aliasing, never miss it.
- **`g_csh_on` handles the race.** The getenv initialisation uses a CAS from -1, `csh_set` calls `csh_on()` before its store,
  and `csh_take` skips moved dispatches whatever the switch says. Turning the switch off in the middle of a submission
  therefore cannot run a moved dispatch twice (nvn_cs_hoist.inc:44-58).
- **The probe is strong.** 413 checks, negative controls that must fail, and each rule paired with a "moves" twin. The
  last check is that every scan ended in exactly one stop counter.

## Issues

### Critical (Must Fix)

None.

### Important (Should Fix)

1. **A moved dispatch drops uniform snapshots and flushes renamed updates before the draws it was moved past are
   encoded. The memory-range check does not see this.**
   - **Files:**
     - nvn_cs_hoist.inc:130-149 (`csh_cs`) and :228 (`csh_hit`)
     - mechanism in nvn_mtl.m:14629 (`encode_args`: `usnap_drop` for each writable SBUFP)
     - nvn_mtl.m:1685-1700 (`usnap_drop` drops every whole merged entry it overlaps)
     - nvn_mtl.m:2677-2685 (`usnap_take` merges uniform ranges up to 256 B apart, up to 1 MiB)
     - nvn_mtl.m:20132 and 2961-2986 (`upd_guard_stage` → `upd_flush` copies *all* renamed updates to memory and drops
       their snapshot entries)
     - nvn_mtl.m:14477 (graphics uniforms read the snapshot through `usnap_find`)
   - **What's wrong:** `csh_hit` compares the dispatch's storage-buffer range with the draws' guest ranges. A draw D1 in the
     stretch can bind a uniform range U that does not overlap the dispatch's write range W, but shares a merged snapshot
     entry with W. That happens whenever W is also bound as a uniform somewhere in the submission and lies within 256 B of
     U, which is the common "compute writes constants that later draws read" layout. The two orders then differ:
     - Before the branch, D1 was encoded before the dispatch and read the submit-time copy.
     - Now the dispatch's `encode_args` marks the entry `US_DROPPED` first, so D1 reads live memory.

     The same happens through `upd_flush` when W overlaps any pending renamed update. All renames are then written to memory
     and their entries dropped, and D1's bytes outside the updated range come from live memory.
   - **Why it matters:** The snapshot exists because the game rewrites constant pools on other threads while a submission
     is being replayed (nvn_mtl.m:1587-1594, the TOTK "rock walls" bug: distant meshes drawn in front of the camera). If the
     CPU rewrote U before the scan, D1 now draws with another object's constants for one frame. That is the spec's first
     anti-goal (visible change or misplaced geometry for a frame), and the switch is on by default.
   - **How sure:** I found no in-game case. The race needs the CPU to rewrite U during the replay, so a still-camera A/B and
     the `flag cs_hoist` image check would not show it. The path is real in the code I read, and it applies to BotW too:
     `hle_nvn.c:2924` takes the snapshot for every game on this runtime.
   - **Fix (cheap):** in `csh_cs`, for each SBUFP write range, either:
     - (a) when `usnap_on()`, add the full `[lo, hi)` bounds of every snapshot entry it overlaps that is not yet dropped to
       `wr` (binary search with `usnap_first`), so `csh_hit` refuses when a draw before it reads any part of a dropped
       entry; or
     - (b) refuse the dispatch when it overlaps any entry that is not dropped.

     Also refuse (stop 2) when `g_nupd && upd_overlap_seq(W)`, because the dispatch would flush renamed updates. Add a probe
     scenario: two uniform ranges 64 B apart, so they share one copy. Bind one as the dispatch's storage and have the earlier
     draw read the other; the CPU rewrites the other after the snapshot. The draw must still see the snapshot bytes. The
     negative control is the current code.

2. **Default-on scope is wider than the evidence (fbb55b56).**
   - **Files:** nvn_cs_hoist.inc:38-42 (`CSH_DEFAULT`), docs/botw-v1.9.0-port.md:580, 600.
   - **What's wrong:**
     - **TOTK:** The spec's success criterion and plan Tasks 4.3 and 5.1 call for a TOTK pass dump, image check and ABBA. The
       ledger records none ("TOTK ABBA deferred (user: BotW only for now)"), yet the hoist is now on by default in TOTK.
       TOTK leans most on virtual pools and render targets in virtual pools: the R13 canonicalisation path and the
       256-pool / 4096-mapping tables, whose overflow silently turns the feature off. That combination has never run in
       TOTK.
     - **BotW 1.6.0:** the spec names it explicitly, and it was not run either.
     - **Docs:** `docs/botw-v1.9.0-port.md:600` still says "Not measured yet: ... iPad", although Task 6 measured the iPad
       on this very build (GPU -0.7%, no regression).
   - **Fix:** either run TOTK once (pass dump plus a `flag cs_hoist` image check is enough to rule out breakage), or keep
     the default off for TOTK (`TOTK_GAME_V143` / non-BotW) until it runs. Either way, the user should accept this
     deviation explicitly. Update the doc line with the iPad result.

### Minor (Nice to Have)

1. **`csh_on` parses the variable as "on only if exactly 1"** (nvn_cs_hoist.inc:46). `TOTK_CS_HOIST=2` or `=yes` turns it
   off even where the default is on. `flag cs_hoist -1` (the toggle convention that `mfx_upscale` uses) turns it on. The
   other switches in this file use `!(e && !strcmp(e, "0"))`.
2. **The probe always forces the switch on.** It calls `setenv("TOTK_CS_HOIST", "1")` (nvn_mtl.m:25036), so the per-game
   `CSH_DEFAULT` has no automated check. Plan Task 5 Step 4 asked for a probe run without the forced `setenv`; only
   `measure.sh botw default` covered it.
3. **The OOT build was not compiled after the change** (R8c, ledger Task 5). Neither were odyssey, acnh and eow, which also
   compile the changed `shared/.../totk_vpool.c` through symlinks. Reading the code, I see nothing that would break. Still,
   one compile of OOT (the same `nvn_mtl.m` with `GAME_OOT`) and of one other game before merge is cheap insurance.
4. **`totk_vpool.c` is shared with four other games,** and the new "table full ... no longer told apart" red log
   (totk_vpool.c:37) also fires in games that never use the hoist. More than 256 virtual pools is enough to trigger it. The
   message should say it only affects the compute hoist.
5. **The rescan reason is counted under the wrong name.** A rescan that stops at a dispatch already run ahead is counted
   as `dispatch_refused` (stop 2, nvn_cs_hoist.inc:223). That mixes "already moved" with real refusals in the statistics
   line. A separate counter, or a note in the comment, would keep the BotW tuning numbers honest.
6. **The full scan takes `registry_lock` once per sampled texture of every scanned draw** (`csh_tex`,
   nvn_cs_hoist.inc:70-73). This only costs time: the game thread grows `g_treg` under the same lock. The submit cost was
   measured flat in BotW, but the cost is worth watching in TOTK.
7. **`vmap_cut`'s split and head-trim branches, the overflow path and `fini` have no probe assertion** (deferred R13
   minor). I hand-traced them and they are correct. They now decide aliasing for the hoist, and `probe-vpool` could check
   them in a few lines.

## Deferred minors triage

| Ledger line | Rating |
|---|---|
| T1: attachment-storage check missing | Closed: done in Task 2 (`csh_attachment_hit`, scenarios Z and Z2) |
| T1: no T1 probe for `csh_hit` | Closed: scenarios B, T2, R1, R2 and AL* |
| T1: `csh_prog` resolves through `g_prog_prefetch` before `dispatch()`'s `prog_get(g_prog_for_draw=1)` | Fine to leave. `shader_predict_rest` uses the same pattern. A draw that cannot be skipped still waits through `prog_resolve(pr, draw_may_skip(pr))` (nvn_mtl.m:19169), and the comment is in place. |
| T1: `g_tex_hi` grows during the scan and is not restored | Fine to leave: a high-water mark, at most a few extra slots compared |
| T2: D/E assert reason 8, which cannot fail | Fine to leave (test precision only). Passing -1 would be more honest. |
| T2: range budget (all 16 `S.vbuf` slots, stale size-0 streams stop the scan) | Fine to leave: performance only (R10, R11). Revisit if TOTK stop 0/1 counts dominate. |
| T2: optional `pr->keeps` refusal | Fine to leave. This fork has no transform feedback (nvn_geometry_rt.inc:19, hle_nvn.c:2238). Global stores show up in the reflection as SBUFP rw, GMEM or IMG, which already stop the scan. Recommended anyway as a one-line guard that matches the spec's wording. |
| T2: CBUF `reg >= 16` refuses `NVN_PUSH_BANK` (OOT only) | Fine to leave: conservative, and OOT is off by default |
| T2: scenario U relies on `lp_end` writing an 8-byte header | Fine to leave (test fragility) |
| T2: `geo_access_stage` treats UBOP as unknown (cleanup elsewhere) | Fine to leave: outside this branch |
| T2: the vpool-alias entry refusal has no scenario | Closed or obsolete: R13 removed that refusal, and scenarios AL1-AL5 cover canonicalisation |
| T3: stop 10 (scan limit) never exercised | Fine to leave |
| R13: `vmap_cut` split and head-trim, overflow, `csh_tex_alias` unknown size, `fini`, the every-20000 trigger untested | Fine to leave. Hand-traced correct; adding a `probe-vpool` assertion is recommended (Minor 7). |
| R13: the index range `count*4+16` over-estimate | Fine to leave (performance only) |
| R13: a full mapping table also refuses ranges outside any virtual pool | Fine to leave (conservative) |
| R16: one mapping snapshot per scan | Fine to leave. A remap racing a scan of a few microseconds would already race the normal replay. |

**Must-fix deferred minors: none.** The must-fix items are the two new Important findings above.

## Commits the controller wrote without a task review

- **87133266** (`flag cs_hoist`, `csh_set`, atomic `g_csh_on`): correct.
  - `csh_set` initialises from the environment before it stores, so a later getenv CAS cannot undo the switch.
  - `csh_take` ignores the switch, so a mid-submission off neither re-runs nor drops a moved dispatch.
  - The atomics are relaxed, which is enough for a single flag word.
  - Only nit: Minor 1 (the value parsing).
- **fbb55b56** (default on except under `GAME_OOT`, docs): the `#ifdef GAME_OOT` is right. `GAME_OOT` is already used
  inside `nvn_mtl.m` (`oot_bar_allowed`, `ind_split`), so it is defined where the `.inc` is compiled. The scope and the
  docs are Important 2.

## Recommendations

- Fix Important 1 with the conservative variant: refuse a dispatch whose storage write overlaps any snapshot entry that is
  not dropped, or whose range overlaps a pending renamed update. Then read the BotW `dispatch_refused` share in one
  `measure.sh botw default` run. If moves fall a lot, switch to the more precise widening of `wr`.
- After that, one TOTK run with `passdump 3`, plus a `flag cs_hoist` 0/1 screenshot pair, settles Important 2 cheaply.
- Keep the `[cs-hoist]` statistics line. It will show whether TOTK overflows the virtual-pool tables (every scan stopping
  at `first_draw`).

## Declined to judge

- Mesh draws, indirect dispatches and the game-barrier dispatch mode (`DM_NVN_DISPATCH_BARRIER=game`, the OOT default) are
  OOT validation items, because the hoist is off there by default. In game mode, a dispatch moved across a top-level-list
  boundary or next to an earlier dispatch in the shared encoder could lose the ordering that the render pass used to give.
  That needs checking before OOT turns it on.
- TBDR-only mechanisms (`hoist_try`, `fuse_try`, `rt_want` extrapolation, `zskip`) are refused at entry through
  `tbdr_on()`, and TBDR is off by default. I did not judge them further.
- Prompt-icon texture swaps (`totk_prompt_revision`, which bumps `g_reg_gen` at every list entry) could in principle
  change the texture behind a handle between the scan and the dispatch's original place. A compute shader sampling a UI
  prompt icon is implausible, so I set this aside.
- I did not check any measured performance claims (ABBA, iPad) beyond reading the ledger. The instructions say not to
  re-run validation.
- The spec's optional extension across same-target `SET_RT` (`TOTK_RT_CONTINUE`) is left open by design.
- A remap of virtual memory racing the replay (R16) is an accepted preexisting race. I did not judge it beyond the snapshot
  logic.

## Assessment

**Ready to merge? With fixes**

**Reasoning:** The port is careful and well guarded. The submission-scoped skip list, the S/R restore, the entry refusals
and the virtual-pool canonicalisation are sound in the code I read. One correctness path is still open: running the
dispatch early also drops uniform snapshots and flushes renamed updates for ranges wider than its write range, ahead of
the draws it was moved past. That is a frame-level risk of wrong constants, and it falls under the spec's first anti-goal.
Separately, default-on for TOTK has no in-game evidence behind it.
