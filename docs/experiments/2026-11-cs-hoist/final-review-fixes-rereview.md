# Re-review: compute-dispatch hoist final-review fix wave (fbb55b56..c0052f1e)

Read-only seat, no subagents. Inputs: final-review.md, fixwave-brief.md, fixwave-report.md, review package
review-fbb55b56..c0052f1e.diff. I checked the code around every side effect of `dispatch()` / `encode_args` in the worktree.
I ran no tests (the report shows the probe output, the pre-fix failure and the negative controls, and reading the code
raised no doubt that a run would settle). Line numbers are for HEAD c0052f1e.

## Finding Verdicts

- **Important 1: a moved dispatch drops uniform snapshots and flushes renamed updates ahead of the draws it jumps.**
  ADDRESSED.
  - The new `csh_uniform_hit` (nvn_cs_hoist.inc:164) is called beside `csh_hit` at nvn_cs_hoist.inc:252. A hit counts
    as stop 3 (memory_conflict).
  - **Snapshot side.** The rule copies `usnap_drop`'s own loop (nvn_mtl.m:1699): `usnap_first(lo)` while
    `g_usnap[k].lo < hi`, on the same `[addr, addr + (size ? size : 1))` that `encode_args` drops for a writable SBUFP
    (nvn_mtl.m:14629). Any entry that overlaps and is not US_DROPPED refuses the dispatch.
    - So the judgement is by the merged entry, not by the dispatch range. A moved dispatch can only "drop" entries
      that are already dropped, which means it changes no snapshot state for any draw, whichever part of a copy that
      draw reads.
  - **Rename side.** Every SBUFP with reg < 16 is checked with `g_nupd && upd_overlap_seq` on the same range that
    `upd_guard_stage` (nvn_mtl.m:18218) uses. `upd_guard_stage` checks every SBUFP, read-only ones included, and so
    does the rule.
  - **Every other way `dispatch()` drops or flushes is already refused by `csh_cs`** (nvn_cs_hoist.inc:136-158):

    | Path | Drop or flush | Refused by `csh_cs` because |
    |---|---|---|
    | SBUFU | `upd_guard_stage` (nvn_mtl.m:18221); whole-pool `usnap_drop` (nvn_mtl.m:14608) | default case |
    | TBUF | `upd_guard_stage` (nvn_mtl.m:18225) | default case |
    | GMEML | `gml_take` → `usnap_drop(0, UINT64_MAX)` (nvn_mtl.m:13078) | default case |
    | IMG | `bright_lut`; texture writes | default case |
    | Built-in kernels | `upd_guard` on ubo0 / ssbo0 / ssbo1 (nvn_mtl.m:20135) | `cs->builtin` |
    | Indirect | `upd_guard` (nvn_mtl.m:20081) | `dp->indirect` |
    | TEXP / SAMPP | `pool_inputs_wait` → `upd_flush` (nvn_mtl.m:14038) | default case |

    - **TEXP / SAMPP, traced.** `pool_inputs_wait` is reached only through `pool_inputs_wait_range`, from
      `pool_uniform_read` and `pool_demand_prepare` (nvn_mtl.m:14077 and :14162). Those run only from
      `prepare_shader_pools`, which returns at once unless `shader_uses_pool` (TEXP / SAMPP; nvn_mtl.m:13635, :14219),
      and from `descriptor_pool_for_shader`, also TEXP / SAMPP only.
    - **Other dispatch-path calls.** `prepare_shader_images` touches IMG bindings only (nvn_mtl.m:17277), and
      `td_compute` is a texture-dump diagnostic. Neither drops a snapshot copy nor flushes an update.
    - CBUF / UBOP and TEX only read: `upd_shadow`, `usnap_find`, and a texture lookup.
    - **Sweep.** I swept `usnap_drop`, `upd_flush`, `upd_guard`, `upd_insert`, `US_DROPPED` and `pool_inputs_wait`
      across the whole `games/totk/third_party/d2r_gfx/gfx/nvn` directory, not just `nvn_mtl.m`. The hits outside
      `nvn_mtl.m` are:
      - probe headers;
      - the mesh `.inc` files (mesh draws, not dispatches);
      - `nvn_raw_write_domain.inc`, the GMEML write log, which `csh_cs` refuses.

      Inside `nvn_mtl.m`, the remaining hits are `mtl_sub_copy`, the inline update, `copy_t2b`, the CPU-wait drop, the
      snapshot copy-fault path (nvn_mtl.m:2724, the helper thread's own copy) and the end-of-submission flush in
      `mtl_sub_commit` (nvn_mtl.m:3549-3550). None of them is reachable from a dispatch that `csh_cs` accepts.
  - **Ordering.**
    - Snapshot entries are made only at submit time: `hle_nvn.c:2924`, and `nvn_queue_order.inc:219` for a resumed
      item, both before `mtl_exec`. During a replay an entry can only go to DROPPED. So no entry can be created later
      in the scan.
    - Renamed updates enter the log only through `upd_insert`, whose sole caller is `mtl_sub_update`
      (nvn_mtl.m:3041). In the replay, `mtl_sub_update` is reached through OP_UPDATE_UB (nvn_mtl.m:21098), which
      `csh_stop_op` treats as a stop. More generally, only state commands, draws, dispatches and barriers without bits
      get past the scan. No update can appear between the scanned draw and the dispatch.
    - Draws that write memory stop the scan, so no draw in the stretch drops anything.
    - Earlier dispatches moved in the same scan passed the same rule, so they neither dropped nor flushed anything.
    - The state the rule judges is therefore exactly the state the early `dispatch()` call meets.
  - **S/R match.** The rule reads `S.ssbo[5]` after `state_op` has applied every state command up to the dispatch, and
    `dispatch(dp)` runs right after with the same `S`.
    - The rule's shader is `cpr->sh[5]`, where `cpr = csh_prog(S.cprog ? S.cprog : S.prog)`. That is the program
      `dispatch()` takes through `prog_get(cp)`, and compute has no variant selection.
    - The reg >= 16 skip matches `encode_args` (u = NULL) and `csh_cs` (returns 0).
  - **Probe.**
    - SN puts the draw's U and a 16-byte uniform at the start of W in one merged copy, and asserts `cw == cu`
      (nvn_mtl.m:25275). It checks the pixels against the submit-time colour.
    - Pre-fix it failed with pixel 255 against an expected 64 (report). `TOTK_PROBE_NEGATIVE=3` and `=4` fail SN / RU.
      The twins SN2 / RU2 move.
- **Important 2: default-on scope wider than the evidence.** ADDRESSED.
  - `CSH_DEFAULT = 1` only under `#ifdef GAME_BOTW` (nvn_cs_hoist.inc:43-47).
  - Every BotW gfx build defines it: Makefile:477 and :493, and the iOS `build_ipa.py`. No TOTK, OOT or NS2 build does.
    The OOT, DKB and Pokopia IPA path defines `GAME_OOT` / `GAME_DKB` / `GAME_POKOPIA` plus `GAME_NS2`.
  - The comment above `CSH_DEFAULT`, the header comment and docs/botw-v1.9.0-port.md:582 / :604 are updated. The stale
    "Not measured yet: ... iPad" sentence is replaced with the brief's A16 numbers.
- **Minor 1: `TOTK_CS_HOIST` parsing.** ADDRESSED. `strcmp(e, "0") != 0` (nvn_cs_hoist.inc:51): 0 is off, any other
  value is on, the same as the file's other switches.
- **Minor 2: the probe forces the switch on.** NOT ADDRESSED, and left on purpose (brief item 4). The report notes it.
- **Minor 3: OOT and the other games compiled after the change.** ADDRESSED, per the report and not re-run by me.
  - Compiled as objects: OOT `nvn_mtl.m.o` and `totk_vpool.c.o`, Odyssey `totk_vpool.c`, BotW 1.6.0 and 1.9.0.
  - Not built: acnh, eow, and full links.
- **Minor 4: the vpool "table full" red log fires in games that never run the hoist.** ADDRESSED.
  - `vmap_lose` only records what overflowed (totk_vpool.c:40).
  - `totk_vpool_view_sync` logs once per view, when it first sees the loss (totk_vpool.c:75). Its only caller is the
    hoist (nvn_cs_hoist.inc:227).
  - Every overflow path bumps `g_map_gen`: totk_vpool.c:59 before `vmap_note`'s lose, :120 after the pool one, and
    :133. So a view always re-syncs and sees the loss.
- **Minor 5: a rescan stopped at a dispatch already run ahead is counted as `dispatch_refused`.** ADDRESSED.
  - Stop 12 `already_moved` (nvn_cs_hoist.inc:247), `CSH_STOPS` 13, and 13 names (:37).
  - The probe's sum check covers 0-7 and 10-12 (nvn_mtl.m:25351). Scenario I asserts the counter rises
    (nvn_mtl.m:25113).
- **Minor 6: `registry_lock` per sampled texture.** NOT ADDRESSED, and left on purpose (brief item 4, perf only).
- **Minor 7: no probe assertion for `vmap_cut` split / head-trim / overflow / fini.** NOT ADDRESSED. The brief does not
  scope it, as either a fix or a leave, and it does not block this round.

## New Breakage in the Fix Diff

- **Critical / Important:** none.
- **Minor:** the RU / RU2 probe assumes `mtl_sub_update` renames the update. It does not assert `g_nupd > 0` after the
  call (nvn_mtl.m:25277).
  - With `TOTK_UB_RENAME=0`, or with the pending table full, `mtl_sub_update` drops U's copy at once
    (nvn_mtl.m:3046-3047). RU would then fail on the pixel with a misleading message.
  - It fails loudly, so it is not a silent pass. SN has the matching `usnap_on()` guard (nvn_mtl.m:25265).
- **Minor (commit hygiene, from the report):** the docs sentence for the uniform rule landed in 60871420 / c0052f1e, not
  in abfee4e0.

## Out-of-Scope Observations

- The rule is the conservative variant: it refuses any writable storage buffer inside a live snapshot copy, even when
  no draw in the stretch reads that copy. The BotW move count measured before the rule may fall.
  - This costs performance only. The implementer already flags it: one `measure.sh botw default` run, then read the
    `memory_conflict` share.
- The reverse direction is likely benign and was not judged. A draw in the stretch whose vertex, index or read-only
  storage range overlaps a pending update makes `upd_guard_draw` flush every update before the dispatch's original place.
  - Run early, the dispatch then reads its own uniforms through the private copy or the snapshot (submit-time values).
    In its original place it read live memory after the flush.
  - This predates the fix diff.

## Verdict

**Fix round:** All findings addressed, no new Critical/Important breakage. Important 1, Important 2 and Minors 1, 3, 4
and 5 are addressed. Minors 2 and 6 are left as the brief says. Minor 7 is unscoped.
