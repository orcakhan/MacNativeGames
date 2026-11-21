# Fix-wave report: compute-dispatch hoist (final-review findings)

Status: DONE_WITH_CONCERNS. Base fbb55b56, branch orcakhan/nxnative.

## Commits
- abfee4e0 fix: the compute-dispatch hoist leaves a dispatch in place when running it early would change the uniforms the draws before it read
- 60871420 perf: compute dispatches run ahead of the pass by default in BotW only
- a91151a9 fix: TOTK_CS_HOIST turns the compute-dispatch hoist off only for 0, as the file's other switches read
- 42c59ae4 fix: the virtual-pool "table full" warning prints only where the compute-dispatch hoist reads the tables
- c0052f1e fix: the compute-dispatch hoist counts a rescan stopped at a dispatch it already moved as already_moved

## What changed
1. Important 1 (abfee4e0). New `csh_uniform_hit(cs)` in nvn_cs_hoist.inc, called in csh_try beside csh_hit (stop 3,
   memory_conflict). It checks the dispatch's SBUFP bindings by raw guest address, exactly as the side effects do:
   - writable SBUFP: refused when [addr, addr + (size ? size : 1)) overlaps any g_usnap entry not US_DROPPED (usnap_drop's own
     loop: usnap_first / lo < hi), i.e. judged by the merged entry, not the dispatch range;
   - every SBUFP (rw or not, as upd_guard_stage guards them all): refused when g_nupd && upd_overlap_seq(range).
   SBUFU / TBUF (which upd_guard_stage also guards) are already refused by csh_cs. General: no game or shader rules.
   Probe scenarios (nvn_mtl.m, mtl_probe_cs_hoist, own memory m3, a real fragment argument buffer reading a CBUF):
   - SN: the submission's snapshot holds the draw's uniform U (32 B) and a uniform range at the dispatch's storage W start
     (merged copy, 224 B apart, asserted). CPU rewrites U's second float4 after the snapshot. Expect: refused, 2 passes,
     left-half pixels = submit-time colour (64,128,191,255), W[0] +1.
   - SN2 (twin): W in no copy: moves, same colour.
   - RU: renamed updates over U's first float4 and inside W (W in no copy): refused, submit-time colour.
   - RU2 (twin): no update in W: moves, same colour.
   Pixels are checked before the counts. Negative controls: TOTK_PROBE_NEGATIVE=3 (snapshot rule off) and =4 (renamed rule
   off).
2. Important 2 (60871420). CSH_DEFAULT = 1 under GAME_BOTW only, 0 otherwise (TOTK, OOT). Comment above CSH_DEFAULT, header
   comment and docs/botw-v1.9.0-port.md section updated (BotW only; TOTK and OOT off until measured; iPad A16 result with the
   brief's numbers, replacing the stale "Not measured yet" sentence; the uniform rule; check count; a sentence that the
   measurements predate the uniform rule).
3. Minors fixed:
   - TOTK_CS_HOIST: `strcmp(e, "0") != 0` (0 off, any other value on); comment and docs say so (a91151a9).
   - vpool "table full" log moved from vmap_lose to totk_vpool_view_sync (only caller: the hoist), printed once per view when
     it first sees the overflow, text now says the hoist moves nothing from then on. Games that never run the hoist print
     nothing (42c59ae4).
   - New stop counter 12 `already_moved` for a rescan stopping at a dispatch already run ahead (was dispatch_refused);
     CSH_STOPS 13, names, comments, probe sum check (0-7, 10-12); scenario I asserts the counter rises (c0052f1e).
4. Minors left (as the brief says): registry_lock per sampled texture in csh_tex (perf only, watch in TOTK); the probe forces
   TOTK_CS_HOIST=1, so CSH_DEFAULT per game has no automated check.

## Verification (commands and tails)
- Pre-fix (scenario added, fix absent):
  `make -C games/totk probe-gpu-cs-hoist PROBE_ROOT=/Users/luisz/MacNativeGames-work/totk/totk/` exit 2:
  `cs-hoist probe SN ...: 1 passes, 1 dispatches moved ahead` / `FATAL cs-hoist probe SN draw reads a snapshot copy the
  dispatch writes into: pixel 0,0 channel 0 = 255, expected 64 (the colour of the submit call)`.
  (Baseline before any change: pass, 413 checks.)
- Final: same command exit 0, `"status":"pass","probe":"probe-gpu-cs-hoist","checked":946`; SN 2 passes / 0 moved, SN2 1 / 1,
  RU 2 / 0, RU2 1 / 1; stats line `moved=13 scans=40 ... memory_conflict=11 ... already_moved=1`.
- Negative controls on the final binary (build/totk-native-v143 ... probe-gpu-cs-hoist with TOTK_PROBE_NEGATIVE=n), all exit 134:
  - 1: `FATAL cs-hoist probe A: s0[0] = 2 after the submission, expected 1`
  - 2: `FATAL cs-hoist probe A draw, dispatch, draw: 2 passes / 0 moved, expected 1 / 1`
  - 3: `FATAL cs-hoist probe SN ...: pixel 0,0 channel 0 = 255, expected 64`
  - 4: `FATAL cs-hoist probe RU dispatch's storage under a renamed update: pixel 0,0 channel 0 = 255, expected 64`
- `make -C games/totk probe-gpu-ubo-snapshot ...`: pass, 16409 checks. `probe-gpu-ub-rename`: pass, 3956 checks.
- Compile checks (exit 0, no errors):
  - TOTK gfx (build/gfx, via the probe build of build/totk-native-v143);
  - BotW: build/gfx-botw and build/gfx-botw190 nvn_mtl.m.o and totk_vpool.c.o;
  - OOT (GAME_OOT; same nvn_mtl.m through the games/oot/third_party/d2r_gfx symlink): nvn_mtl.m.o, totk_vpool.c.o with
    WORK=<scratchpad>/ootwork;
  - Odyssey: totk_vpool.c (the shared file, via symlink) rebuilt from scratch, exit 0, no errors. Odyssey's nvn_mtl.m is its
    own copy, not this one, so only totk_vpool.c matters there.
  Full links of the BotW / OOT / Odyssey binaries were not run (object compiles only). acnh and eow not built.
- `make -C games/totk probe-gpu-dispatch-chain ...`: pass, 255 checks (TOTK binary, hoist now off by default there).
- No stats-line consumers found in the repo (git grep for dispatch_refused / scan_end / "[cs-hoist]" outside the two sources
  and the docs); no other stale default statements (git grep cs_hoist / CS_HOIST outside nvn/: only mk8d / ss, which have
  their own unrelated DM_NVN_CS_HOIST).
- No game windows were launched.

## Concerns
- The BotW numbers in the docs (6-7 moves per frame, GPU -1.4%; iPad -0.7%) were measured before the uniform rule. The rule
  refuses any dispatch whose writable storage lies in a live snapshot copy, which is the "compute writes constants later
  draws read" layout; BotW's move count may fall. Not re-measured (no game runs allowed): one `measure.sh botw default` run
  and a look at the `memory_conflict` share is needed. If moves drop a lot, the more precise variant (widen the write
  ranges by the copy bounds and compare with the draws' reads) is the fallback the review describes.
- GAME_BOTW covers BotW 1.6.0 too (build/gfx-botw), which has never been run with the hoist (the review noted it).
- TOTK is now off by default; the TOTK pass dump / image check / ABBA from the plan remain undone.
- The moved vpool "table full" warning has no probe that overflows the tables; checked by reading only.
- Docs edits for the rule sentence and check count landed in the default-scope commit (60871420) and c0052f1e, not in
  abfee4e0.
