# SDD ledger — plan: docs/superpowers/plans/2026-11-19-compute-hoist.md

Spec: docs/superpowers/specs/2026-11-19-compute-hoist-design.md (approved 2026-11-19).
Split agreed with the user: Task 0 and Tasks 4-6 by the controller (they run the user's games on this Mac); Tasks 1-3 by subagents.
Local excludes: /.superpowers/ and /docs/superpowers/ in .git/info/exclude (kept out of commits and the upstream PR).
Base before Task 1: 778ab5f9 (origin/main).

## Pre-flight scan

| Pair / task | Produces vs consumes | Finding |
|---|---|---|
| T1 → T2 | T1 `csh_try` with SBUFP/CBUF-only reads; T2 adds `csh_draw_reads`/`csh_cs` (`csh_rng`) | consistent; T2 replaces T1's narrow rules |
| T1 → T3 | T1 declares `g_csh.stop[10]`; T3 fixes the index meanings | T1 would increment stops before their meaning exists → ruling R1 |
| T1 → T2/T3 probe | `mtl_probe_cs_hoist`, `g_csh_probe_neg` | consistent |
| T1 internal | Global Constraints: stop at UPDATE_UB / RENDER_COND / RENDER_ENABLE / TF_STATE; T1 step 4 says state via `state_op`, which accepts RENDER_COND/RENDER_ENABLE | ruling R2 |
| T1 internal | default off until T5 vs probe `setenv("TOTK_CS_HOIST","1")` before first `csh_on()` | consistent (fresh probe process) |
| T2 internal | scenario F uses NvProg `missing` (exists: `cpr->missing` in dispatch()) | consistent |
| T3 internal | "probe must pass unchanged" | consistent |
| T4/T5 | controller; measure.sh from T0 | consistent |

Ruling R1: T1 already uses T3's stop-index table (0 first draw, 1 later draw, 2 dispatch refused, 3 memory conflict, 4 dispatch limit, 5 other op or barrier, 6 bad cursor, 7 depth already written, 8 pre-scan found no dispatch, 9 entry refusal); T3 only adds the log/PD lines — the plan defines the table once, so using it early costs nothing — if wrong, T3 renumbers.
Ruling R2: both the pre-scan and the full scan test OP_UPDATE_UB, OP_RENDER_COND, OP_RENDER_ENABLE, OP_TF_STATE and OP_BARRIER(bits) as stops before calling state_op — Global Constraints are binding over the step wording — if wrong, a moved dispatch could cross a render condition.

## Progress

- Task 0: script written ($SCRATCH/measure.sh); verification run `botw base2` in progress.
- Task 0: verification run aborted at the user's request (2026-11-19, they are using the Mac; no game windows until they allow).
Ruling R3: Tasks 1-3 run before Task 0's verification — Task 0 only gates Task 4's measurements — if the script is wrong, only Task 4 waits.
- Task 1: dispatched (base 778ab5f9, implementer opus, brief task-1-brief.md, report task-1-report.md).
User constraint (2026-11-19): CPU/GPU use is fine; nothing that plays audio or comes to the front (no game windows) until they allow.
- Task 1: implementer DONE_WITH_CONCERNS, commit 4f1b9cfb. Concerns triaged:
Ruling R4: accept the extra entry refusal g_defer_nact — a deferral can be active with TBDR off; refusing is the spec's 'refuse when uncertain' — costs only missed moves.
Ruling R5: OP_TF_STATE does not exist in this fork; 'any op state_op does not take' covers transform feedback — nothing to do.
Ruling R6: Task 1's draw rule refusing vbuf/ibuf/indirect/mesh draws is Task 2 scope (Task 2 Step 3 lists vbuf/ibuf reads) — carried to Task 2's dispatch.
Ruling R7: the 4096-op limit and a normal scan end get counters in Task 3 (stop[10] 'scan limit', stop[11] 'scan reached end'; g_csh.stop grows to 12) — the plan's table had no slot — costs a renumber in Task 3 only.
Ruling R8: Task 2 must (a) check attachment-storage overlap and virtual-pool aliasing as the nxnative csh_add/csh_attachment_hit do, (b) make the scan judge the shader variant the draw will actually use (or refuse when it cannot know), (c) compile the OOT build of the shared gfx — carried to Task 2's dispatch.
- Task 1 review: Needs fixes (Important 1: a pending moved dispatch can be moved again when the pass fails to open/ends in the stretch; Important 2: no virtual-pool alias guard). Fix round 1 dispatched to the original implementer.
Task 1: minor (deferred): attachment-storage check missing; comment 'draws write no memory' wrong (fix the comment in round 1; check + probe for an SSBO/UBO range over an attachment go to Task 2).
Task 1: minor (deferred): no T1 probe for csh_hit (Task 2 scenario B covers).
Task 1: minor (deferred): csh_prog resolves via g_prog_prefetch before dispatch()'s prog_get(g_prog_for_draw=1) — add a comment; watch in Task 2 scenario F.
Task 1: minor (deferred): g_tex_hi grows during the scan and is not restored (high-water mark, harmless).
Task 1: fix round 1/5 (3 addressed, 0 open — re-run guard, vpool alias guard, comment; commits 4f1b9cf..db3b47b)
Task 1: complete (commits 778ab5f..db3b47b, review clean after round 1)
- Task 2: dispatched (base db3b47be). Carries R6, R8, Task 1 deferred minors (attachment-storage check + probe; csh_prog prefetch note).
- Task 2: implementer DONE_WITH_CONCERNS, commits c16b00e2, a386a8fb. Triage:
Ruling R9: scenario F checks refusal (stop[2], nothing moved) instead of 'runs once' — dispatch() itself skips a missing program, so the original order also runs nothing — no cost.
Ruling R10: a vertex stream with address and size 0 stops the scan (unknown extent) — conservative; Task 4 must check stop[0]/[1] counts in BotW to see if this blocks real moves.
Ruling R11: the 1024-range cap counting as stop[0]/[1] — Task 4 checks TOTK's 41-draw G-buffer stretch.
Note: subagents commit with git directly (Conventional Commits + attribution) instead of the user's /commit skill — skill is user-invoked; content follows its conventions.
- Task 2 review: Approved with Important 1 (three correctness rules unguarded by scenarios: later-draw dwrote, CBUF/UBOP attachment check, unregistered TEX handle). Fix round 1 dispatched.
Task 2: minor (deferred): D/E assert reason 8 which cannot fail — pass -1.
Task 2: minor (deferred): range budget — all 16 S.vbuf slots listed incl. stale streams, no dedupe; a stale size-0 stream stops the scan. Task 4 checks stop[0]/[1]; fix = identical-range merge / only streams S.attr references.
Task 2: minor (deferred): optional pr->keeps refusal in csh_draw_reads.
Task 2: minor (deferred): CBUF reg>=16 refuses NVN_PUSH_BANK (OOT only).
Task 2: minor (deferred): U scenario relies on lp_end writing an 8-byte header.
Task 2: minor (deferred, cleanup elsewhere): geo_access_stage treats UBOP as unknown while its extent is the bound range.
Task 2: fix round 1/5 (1 addressed, 0 open — scenarios C3, Z2, W3; commits a386a8f..bed9630)
Task 2: complete (commits db3b47b..bed9630, review clean after round 1)
Task 2: minor (deferred): the vpool-alias entry refusal has no scenario.
- Task 3: dispatched (base bed96301), carries R7 (stop[10] scan limit, stop[11] scan reached end; g_csh.stop grows to 12).
- Task 3: implementer DONE, commit fa9828da; review dispatched. Task 0 verification started (user freed the Mac 2026-11-19).
Task 3: complete (commits bed9630..fa9828d, review clean)
Task 3: minor (deferred): stop 10 (scan limit) never exercised by the probe; stop 11 is (scan_end=7 in the probe's printed line).
- Task 0: verification run base2 (Mac free): frame p50 8.84 ms (113.1 fps) [8.66..9.04], GPU 7.91, submit 5.68, 12 same-target breaks/frame, same scene and settings as the 13:53 baseline (11.30 ms, 88.5 fps, submit 7.1).
Ruling R12: the 13:53 baseline was CPU-contended (the user was using the Mac); base2 replaces it; the hoist is judged only by same-session ABBA, never against the old baseline — if wrong, ABBA still compares like with like.
- Task 4 (BotW ABBA, paused by the user after off1/on1/on2): with TOTK_CS_HOIST=1 nothing moved (H 0/frame, same-target breaks 14-16/frame). Cause from the pass dump: virtual-aliases=1 in BotW, so Task 1's entry refusal totk_vpool_aliases_used() refuses every scan. Also seen: the 2560x1440 G-buffer break has a dw=1 draw before a dispatch sampling the pass depth (stop[7], correct).
Ruling R13 (plan defect found in Task 4): replace the global alias refusal with per-range canonicalisation through the virtual-pool map (compare physical backing addresses; refuse a range in a virtual pool that is not wholly inside one mapping); and print the stats MLOG periodically even with zero moves — Task 1's coarse guard makes the feature a no-op in BotW; precise canonicalisation keeps Important 2's safety — if wrong, an aliased conflict could move (guarded by a new probe scenario with real aliases).
- R13 fix: implementer DONE_WITH_CONCERNS, commits 00db0c13, ad2e628a. Triage:
Ruling R14: accept ranges across adjacent mappings whose physical memory is contiguous (AL2b/AL2c) — the canonical range is then one contiguous physical range, which is exactly what R13 compares — no cost.
Ruling R15: ranges over scattered physical pages stay refused for now; measure BotW's stop counts first; implement one-range-per-mapping-piece only if stops 0/1/2 dominate — avoids speculative complexity — costs another round if BotW needs it.
Ruling R16: per-scan mapping snapshot accepted (a remap racing a microsecond scan); overflow path = old total refusal, logged once — deferred minors.
R13 fix: complete (commits fa9828d..ad2e628, review clean, approved)
R13 fix: minor (deferred): vmap_cut split/head-trim branches, overflow path, csh_tex_alias unknown-size branch, fini cleanup and the every-20000 trigger have no probe assertion.
R13 fix: minor (deferred): index range count*4+16 over-estimate may give spurious stop 0/1 at mapping/pool borders (perf only).
R13 fix: minor (deferred): a full mapping table also refuses ranges outside any virtual pool (conservative).
- Task 4: waiting for the user to free the Mac to rerun the BotW ABBA with apps updated to ad2e628a.
- Task 4 (new BotW save 19/11 18:13, user's choice: one pair, on then off; ad2e628): on 10.92 ms (91.5 fps) [10.48..11.45], GPU 7.83 [7.72..7.90], submit 17.94 M; off 11.29 ms (88.6 fps) [10.63..12.07], GPU 7.98 [7.85..8.13], submit 17.54 M. Passes/frame 144 -> 132, same-target dispatch breaks 13.7 -> 9.3, H 5.3/frame. Stats: moved 95784, depth_written 44216, entry_refused 242529, other_op 95784. No window-covered events. Single pair, order not balanced; image compare not done yet.
- Task 4 ABBA (BotW, user's new settings, 3022x1700, ad2e628): off1 7.95 ms GPU 5.33; on1 7.92 GPU 5.26; on2 7.93 GPU 5.25; off2 7.99 GPU 5.33. Frame -0.045 ms (0.6%, inside the ranges); GPU -0.075 ms (-1.4%, both on runs below both off runs); submit cycles off 18.80 M avg, on 18.98 M avg (+1%, noise level). Same-target dispatch breaks 15-16 -> 11/frame, H 6-7/frame. Frame time is CPU-bound (frame 7.9 vs GPU 5.3). Criterion outcome: fps flat, GPU lower -> stays on, iPad A/B mandatory (Task 6).
- Task 4 image check: screenshot RMSE useless (off1 vs off2 10.4%, on1 vs on2 18.9%: the camera framing and clouds differ between launches); visual inspection of the 4 shots shows no missing or misplaced particles. A same-frame comparison needs a runtime toggle in one session — pending.
Ruling R17: the controller added the test switch "flag cs_hoist <0|1>" itself (commit 87133266, probe 413 checks pass) — a 10-line diagnostic needed only for Task 4's image check; the final whole-branch review covers it — if wrong, the review sends it back.
- Task 4 image check (one session, flag cs_hoist, 3 consecutive screenshots per group, ~6 s between groups): consecutive frames 0.12-0.16% RMSE; same setting 6 s apart on/on 1.74%, off/off 1.66%; on->off 1.45%, off->on 1.44%, on->off 1.43%. On/off differences are no larger than the time noise -> no visible change. Task 4: complete.
- Task 5: default on except GAME_OOT, docs section in docs/botw-v1.9.0-port.md (commit fbb55b56); probe 413 pass; `measure.sh botw default` with no env var: moved > 0 (150000 total, H 3/frame), frame 7.94 ms, GPU 5.32. TOTK ABBA deferred (user: BotW only for now). OOT build not compiled (change is one #ifdef). Task 5: complete.
- Task 6 (iPad A/B): mandatory per the criterion; waiting for the user (needs their iPad).
- Task 6 (iPad A16, BotW-cshoist.ipa from fbb55b56, Wi-Fi, autoload, default 30 fps cap, 1600x900 -> 1920x1080 MetalFX; one warm-up start for 17,878 pipelines first): GPU p50 off1 29.90, on1 29.85, on2 29.79, off2 30.17 (off2 log0 pull failed: last 12 windows used) -> on -0.22 ms (-0.7%), ranges overlap; frame 33.4 ms in all (cap). Submit cycles on 26.3-26.4 M vs off2 26.4 M (off1 24.5 M at a lower CPU plateau, 2.12 vs 2.85 GHz). Hoist moves ~39% of scans; depth_written is the main stop. No regression -> default stays on for iOS. Task 6: complete.
- Final review (opus): ready with fixes; 0 Critical, 2 Important, 7 Minor; deferred minors must-fix: none. Report final-review.md.
Final review I1 confirmed by the controller (nvn_mtl.m usnap_drop drops every snapshot entry overlapping [a,a+n), entries are merged ranges; upd_guard_stage writes all renamed updates): a moved dispatch can strip the submit-time uniform copy from draws before it in game order -> fix in the fix wave with a probe scenario.
Ruling R18 (final review I2): the default is on only under GAME_BOTW (BotW 1.6.0 and 1.9.0 share the gfx build with GAME_BOTW; 1.9.0 measured on Mac and iPad); TOTK joins OOT as off by default until a TOTK run (pass dump, flag cs_hoist image pair, A/B) — the user asked to test only BotW for now; the spec's "on for TOTK" needs that validation — costs TOTK the small GPU saving until then.
- Fix wave: DONE_WITH_CONCERNS, commits abfee4e0 60871420 a91151a9 42c59ae4 c0052f1e; probe 946 checks pass (SN failed pre-fix), ubo-snapshot/ub-rename/dispatch-chain probes pass; BotW/TOTK/OOT/Odyssey objects compile. Concerns: BotW move rate not re-measured after the snapshot refusal; BotW 1.6.0 shares GAME_BOTW and was never run; TOTK checks still undone.
- Fix-wave re-review (opus): I1, I2 and minors 1, 3, 4, 5 ADDRESSED; no new Critical/Important. Left by the brief: minor 2 (probe forces the switch on), minor 6 (registry lock per sampled texture), minor 7 (vmap_cut probe assertions; traced by hand as correct).
Ruling R19: minors 2, 6 and 7 are parked — perf-only or test-only, traced correct by two reviewers — costs a missed regression only if the per-game default or vmap_cut changes later.
- Open before finishing: BotW re-measure after the snapshot refusal (particle save, flagab.sh, waiting for the user); BotW 1.6.0 never run (shares GAME_BOTW); TOTK validation not done (TOTK off by default).
