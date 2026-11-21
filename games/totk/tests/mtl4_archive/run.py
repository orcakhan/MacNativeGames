#!/usr/bin/env python3
"""Phase 0 runs of Breath of the Wild 1.9.0's Metal 4 pipeline archive on the Mac (docs/experiments/2026-11-botw-mtl4-archive),
with archive.py. Mac only. Every run uses a game binary under a test bundle id (org.macnativegames.mtl4test-NNNN): Metal keeps
compiled code per bundle id, and the installed games' (org.macnativegames.totk-native) must not be touched.

  run.py gen  --exe <totk-native-botw190 built with the test plist> --res <app>/Contents/Resources/totk [--reps 3]
              [--lists a.tsv b.tsv ...] --out <jsonl>
      Items 1-3. The pipeline-archive mode as build_app.mac_pipelines runs it (TOTK_PIPELINE_ARCHIVE_HOST=1), two arms of
      the same binary: old (TOTK_PSO_MTL4=0) and new (Metal 4). Per repetition and arm (order alternating): an empty
      folder and a copy under a bundle id no run used (cold), then the same copy into a new folder (warm). After the cold
      run of the new arm a second process looks every key up in a copy of what it made (TOTK_PAR_RECHECK=1): coverage is
      what that run found. Each cold folder is packaged as the App would carry it. Once: "upgrade" (the new arm with
      TOTK_PAR_RECHECK=1 over a copy of the old arm's cold folder, as a rebuild over build/mac-pipelines does) and "death"
      (the new arm with TOTK_PSO4_TEST_DEATH=150, then the check).
  run.py ipad --exe ... --res ... --seed <device seed> --out <jsonl>
      The device mode (no TOTK_PIPELINE_ARCHIVE_HOST, as device_pipelines.make runs it): no pipelines-mtl4 folder, and the
      same .metalarchive keys with the archive on and with TOTK_PSO_MTL4=0.
  run.py game --app-a <old app> --app-b <new app> [--runs 3] [--play-s 120] --out <jsonl>
      Item 4. The game launched directly (the "BotW Mac A/B recipe"), on copies of the profile, cache and settings: one
      launch of each app first (prepares its cache copy, reported apart), then ABAB, each from a new copy of that app's
      prepared cache. App A runs with TOTK_PSO_MTL4=0. The game follows ROUTE and closes play_s seconds after the save started loading.

Prints one JSON summary line."""
import argparse
import json
import os
import re
import secrets
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import archive  # noqa: E402

SUP = Path.home() / 'Library/Application Support/MacNativeGames'
DATA = SUP / 'BotW'
TEST_PREFIX = 'org.macnativegames.mtl4test-'


def cache_root() -> Path:
    return Path(subprocess.run(['getconf', 'DARWIN_USER_CACHE_DIR'], capture_output=True, text=True, check=True).stdout.strip())


def drop_cache(n: int, root: "Path | None" = None):
    """Removes the Metal cache folder of test bundle id n; refuses any other folder (the games' above all)."""
    d = (root or cache_root()) / f'{TEST_PREFIX}{n:04d}'
    if not re.fullmatch(re.escape(TEST_PREFIX) + r'\d{4}', d.name):
        raise ValueError(f'not a test cache folder: {d}')
    shutil.rmtree(d, ignore_errors=True)


def arm_order(reps: int) -> list:
    return [('old', 'new') if r % 2 == 0 else ('new', 'old') for r in range(reps)]


def game_order(runs: int) -> list:
    return [c for _ in range(runs) for c in 'AB']


def fresh_copy(exe: Path, work: Path) -> tuple:
    """A copy of exe under a bundle id no cache folder exists for yet, named so the game slot does not take it for a game
    (runtime/game_slot.c pid_is_game: totk-native*)."""
    root = cache_root()
    while True:
        n = 1 + secrets.randbelow(9998)
        if not (root / f'{TEST_PREFIX}{n:04d}').exists() and n not in (1, 2):   # 0001 / 0002: the game apps (plan Task 5)
            break
    dst = work / f'mtl4-archive-{n:04d}'
    dst.write_bytes(archive.with_bundle_id(Path(exe).read_bytes(), n)); dst.chmod(0o755)
    subprocess.run(['codesign', '-f', '-s', '-', str(dst)], check=True, capture_output=True)
    return dst, n


def pmset() -> str:
    m = re.search(r"Now drawing from '([^']+)'", subprocess.run(['pmset', '-g', 'batt'], capture_output=True, text=True).stdout)
    return m.group(1) if m else '?'


def clone(src: Path, dst: Path):
    subprocess.run(['/bin/cp', '-Rc', str(src), str(dst)], check=True)


def tool_env(res: Path, folder: Path, seed: "Path | None", host: bool, extra: dict) -> dict:
    """The pipeline-archive mode's environment as build_app.mac_pipelines (host) or device_pipelines.make (device) sets it,
    without the shell's own TOTK_ / DM_ settings; extra (a run's own, e.g. TOTK_PAR_RECHECK=1) wins."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(('TOTK_', 'DM_'))}
    env.update(TOTK_SHADER_CACHE=str(folder), TOTK_SHADER_SEED_DIR=str(seed or res / 'build/shader-seed'), TOTK_DEBUG_LOG='1',
               TOTK_PAR_RECHECK='0')
    if host:
        env['TOTK_PIPELINE_ARCHIVE_HOST'] = '1'
    env.update({k: str(v) for k, v in extra.items()})
    return env


def tool(exe: Path, res: Path, folder: Path, lists: list, log: Path, seed: "Path | None" = None, host: bool = True, **extra: str) -> dict:
    env = tool_env(res, folder, seed, host, extra)
    before, t0 = pmset(), time.time()
    with open(log, 'w') as f:
        r = subprocess.run([str(exe), 'rewritten/botw190', 'pipeline-archive', *map(str, lists)], cwd=res, env=env, stdout=f, stderr=subprocess.STDOUT)
    wall = time.time() - t0
    text = log.read_text(encoding='utf-8', errors='replace')
    m4 = host and extra.get('TOTK_PSO_MTL4') != '0'
    out = archive.parse_tool(text, expect_m4=m4)
    out.update(wall_s=round(wall, 2), exit=r.returncode, power=before, power_changed=pmset() != before, log=str(log))
    return out


def app_lists(res: Path) -> list:
    b = res / 'build'
    return [p for p in (b / 'pso_title.tsv', b / 'pso_manifest.tsv', b / 'shader-seed/pso_manifest.tsv') if p.is_file()]


def chain_of(res: Path) -> str:
    return json.loads((res / 'build/shader-seed/seed-manifest.json').read_text()).get('chain', '')


def cmd_gen(a) -> dict:
    res, exe = a.res.resolve(), a.exe.resolve()
    lists = a.lists or app_lists(res)
    work = Path(tempfile.mkdtemp(prefix='mtl4-gen-', dir=a.work)); rows = []
    def emit(row):
        rows.append(row)
        with open(a.out, 'a') as f: f.write(json.dumps(row) + '\n')
        print(json.dumps({k: row.get(k) for k in ('rep', 'arm', 'run', 'wall_s', 'm4_hits', 'm4_built', 'exit')}), flush=True)
    cold = {}
    for rep, order in enumerate(arm_order(a.reps)):
        for arm in order:
            extra = {'TOTK_PSO_MTL4': '0'} if arm == 'old' else {}
            copy, n = fresh_copy(exe, work)
            try:
                f = work / f'{rep}-{arm}-cold'
                r = tool(copy, res, f, lists, work / f'{rep}-{arm}-cold.log', **extra); r.update(rep=rep, arm=arm, run='cold', n=n)
                r['package'] = archive.package(f / 'pipelines', r['report'].get('arch', ''), chain_of(res))
                cold[(rep, arm)] = (f, r)
                if arm == 'new':
                    chk = work / f'{rep}-new-check'; clone(f, chk)
                    c = tool(copy, res, chk, lists, work / f'{rep}-new-check.log', TOTK_PAR_RECHECK='1'); r['check'] = c
                emit(r)
                w = tool(copy, res, work / f'{rep}-{arm}-warm', lists, work / f'{rep}-{arm}-warm.log', **extra)
                w.update(rep=rep, arm=arm, run='warm', n=n); emit(w)
            finally:
                drop_cache(n); copy.unlink(missing_ok=True)
    keys_total = {rep: cold[(rep, 'old')][1]['package']['keys'] for rep in range(a.reps)}
    for rep in range(a.reps):
        r = cold[(rep, 'new')][1]
        r['coverage'] = archive.coverage(r['check'], keys_total[rep])
    for scenario in ('upgrade', 'death'):
        copy, n = fresh_copy(exe, work)
        try:
            f = work / scenario
            if scenario == 'upgrade':
                clone(cold[(0, 'old')][0], f)
                r = tool(copy, res, f, lists, work / 'upgrade.log', TOTK_PAR_RECHECK='1')
            else:
                r = tool(copy, res, f, lists, work / 'death.log', TOTK_PSO4_TEST_DEATH='150')
            r['package'] = archive.package(f / 'pipelines', r['report'].get('arch', ''), chain_of(res))
            chk = work / f'{scenario}-check'; clone(f, chk)
            r['check'] = tool(copy, res, chk, lists, work / f'{scenario}-check.log', TOTK_PAR_RECHECK='1')
            r['coverage'] = archive.coverage(r['check'], keys_total[0])
            r.update(rep=0, arm='new', run=scenario, n=n); emit(r)
        finally:
            drop_cache(n); copy.unlink(missing_ok=True)
    summary = {'work': str(work), 'keys_total': keys_total}
    for arm in ('old', 'new'):
        for run in ('cold', 'warm'):
            ws = [r['wall_s'] for r in rows if r['arm'] == arm and r['run'] == run]
            summary[f'{arm}_{run}_s_median'] = statistics.median(ws)
        p = [r['package'] for r in rows if r['arm'] == arm and r['run'] == 'cold']
        summary[f'{arm}_package'] = p[0]
    for r in rows:
        if r['run'] in ('upgrade', 'death'):
            summary[f'{r["run"]}_package'] = r['package']; summary[f'{r["run"]}_coverage'] = r['coverage']
            summary[f'{r["run"]}_wall_s'] = r['wall_s']
    summary['coverage'] = [r['coverage'] for r in rows if r['arm'] == 'new' and r['run'] == 'cold']
    summary['gave_up'] = [r['gave_up'] for r in rows if r['arm'] == 'new']
    summary['power_changed'] = any(r['power_changed'] for r in rows)
    summary['exits'] = sorted({r['exit'] for r in rows})
    return summary


def keys_in(folder: Path) -> set:
    return {k for p in (folder / 'pipelines').glob('*.keys') for k in p.read_text().split('\n') if k}


def cmd_ipad(a) -> dict:
    res, exe = a.res.resolve(), a.exe.resolve()
    work = Path(tempfile.mkdtemp(prefix='mtl4-ipad-', dir=a.work)); out = {}
    for arm, extra in (('on', {}), ('off', {'TOTK_PSO_MTL4': '0'})):
        copy, n = fresh_copy(exe, work)
        try:
            f = work / arm
            r = tool(copy, res, f, a.lists or app_lists(res), work / f'{arm}.log', seed=a.seed.resolve(), host=False, **extra)
            out[arm] = {'exit': r['exit'], 'wall_s': r['wall_s'], 'keys': len(keys_in(f)), 'mtl4_dir': (f / 'pipelines-mtl4').exists()}
            out[f'{arm}_keys'] = keys_in(f)
        finally:
            drop_cache(n); copy.unlink(missing_ok=True)
    summary = {'work': str(work), 'mtl4_dir': out['on']['mtl4_dir'] or out['off']['mtl4_dir'], 'keys_on': out['on']['keys'],
               'keys_off': out['off']['keys'], 'same_keys': out.pop('on_keys') == out.pop('off_keys'), 'runs': out}
    Path(a.out).write_text(json.dumps(summary) + '\n')
    return summary


def game_env(out: Path, app_res: Path, old: bool, cache_src: Path) -> dict:
    sdir = out / 'MNG/BotW'; sdir.mkdir(parents=True)
    clone(DATA / 'profile', out / 'profile'); clone(cache_src, out / 'cache')
    for f in DATA.glob('*.txt'):
        if f.name.startswith('graphics-') or f.name == 'shadows.txt':
            shutil.copyfile(f, sdir / f.name)
    (sdir / 'graphics-frame.txt').write_text('off\n')
    if (SUP / 'gpu-keepalive.txt').is_file():
        shutil.copyfile(SUP / 'gpu-keepalive.txt', out / 'MNG/gpu-keepalive.txt')
    (out / 'input.txt').write_text(''); (out / 'board').mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('TOTK_', 'DM_'))}
    env.update(TOTK_PROFILE_DIR=str(out / 'profile'), TOTK_SHADER_CACHE=str(out / 'cache'), TOTK_GAME_SLOT_DIR=str(DATA / 'game-slot'),
               TOTK_ROMFS_PROOF_DIR=str(DATA), TOTK_SHARED_FONTS='extracted/firmware/shared-fonts', TOTK_NATIVE_DIR=str(app_res / 'build'),
               TOTK_ROMFS_MODS=str(DATA / 'mods/botw190'), TOTK_CONTROLS=str(sdir / 'controls.txt'), TOTK_PICTURE_MODE=str(sdir / 'picture-mode.txt'),
               TOTK_INPUT_FILE=str(out / 'input.txt'), TOTK_SHADER_CONTRIB=str(out / 'contrib.txt'), TOTK_BOARD_DIR=str(out / 'board'),
               TOTK_CLOUD_SAVE_DIR='0', TOTK_SLOT_OWNER='claude', TOTK_SLOT_PURPOSE='mtl4 archive A/B', TOTK_AUTOLOAD='1',
               TOTK_AGENT_IDLE_S='900', TOTK_DEBUG_LOG='1', DM_NVN_TSV=str(out / 'frames.tsv'), DM_NVN_TSV_CALLS='0')
    if old:
        env['TOTK_PSO_MTL4'] = '0'
    return env


def launch(app: Path, out: Path, old: bool, cache_src: Path, play_s: float) -> dict:
    if subprocess.run(['pgrep', '-f', 'totk-native'], capture_output=True).stdout.strip():
        raise SystemExit('a game is running: the game slot takes one at a time; close it first')
    res = app / 'Contents/Resources/totk'
    env = game_env(out, res, old, cache_src)
    lines, t0 = [], time.time()
    proc = subprocess.Popen([str(res / 'build/totk-native'), 'rewritten/botw190', 'boot'], cwd=res, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', bufsize=1)
    loaded, killed = None, False
    with open(out / 'game.log', 'w') as log:
        for line in proc.stdout:
            t = time.time() - t0; lines.append((t, line.rstrip('\n'))); log.write(f'{t:.3f}\t{line}')
            if loaded is None and '[autoload] load started' in line:
                loaded = t
                route(proc, out / 'input.txt')
                threading_stop(proc, play_s)
            if t > 1200 and loaded is None:
                proc.send_signal(signal.SIGTERM); break
    try:
        proc.wait(15)
    except subprocess.TimeoutExpired:
        proc.kill(); killed = True
    g = archive.parse_game(lines)
    tsv = out / 'frames.tsv'
    g.update(loaded_s=loaded, killed=killed, exit=proc.returncode, opens=archive.parse_tsv_opens(tsv) if tsv.is_file() else None)
    return g


"""The same route for both apps (TOTK_INPUT_FILE keyboard commands, runtime/input_file.h; the fixed scripted layout of
runtime/input.c: W walks, the arrow keys turn the camera): settle 30 s after the save starts loading, turn right 6 s, walk
15 s, turn left 6 s, walk 15 s. Seconds after the load line."""
ROUTE = [(30, 'down 124'), (36, 'up 124'), (37, 'down 13'), (52, 'up 13'), (53, 'down 123'), (59, 'up 123'), (60, 'down 13'), (75, 'up 13')]


def route(proc, input_file: Path):
    import threading
    def run_route():
        t0 = time.time()
        for at, cmd in ROUTE:
            time.sleep(max(0, at - (time.time() - t0)))
            if proc.poll() is not None:
                return
            with open(input_file, 'a') as f:
                f.write(cmd + '\n')
    threading.Thread(target=run_route, daemon=True).start()


def threading_stop(proc, after_s):
    import threading
    def stop():
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
    t = threading.Timer(after_s, stop); t.daemon = True; t.start()


def cmd_game(a) -> dict:
    work = Path(tempfile.mkdtemp(prefix='mtl4-game-', dir=a.work)); rows = []
    apps = {'A': a.app_a.resolve(), 'B': a.app_b.resolve()}
    src = DATA / 'shader-cache/rt-totk-native-v9-unverified'
    prepared = {}
    for c in 'AB':   # preparation: the first launch of each app migrates its keys and warms its bundle id's Metal cache
        out = work / f'prep-{c}'; out.mkdir()
        g = launch(apps[c], out, c == 'A', src, a.play_s); g.update(app=c, run='prep'); rows.append(g)
        prepared[c] = out / 'cache'
        with open(a.out, 'a') as f: f.write(json.dumps(g) + '\n')
    for i, c in enumerate(game_order(a.runs)):
        out = work / f'{i}-{c}'; out.mkdir()
        g = launch(apps[c], out, c == 'A', prepared[c], a.play_s); g.update(app=c, run=i); rows.append(g)
        with open(a.out, 'a') as f: f.write(json.dumps(g) + '\n')
        print(json.dumps({k: g.get(k) for k in ('app', 'run', 'title_s', 'title_wait_s', 'rss_max_mb', 'm4_session', 'exit')}), flush=True)
    meas = [r for r in rows if r['run'] != 'prep']
    col = lambda c, k: [r[k] for r in meas if r['app'] == c and r[k] is not None]
    nlong = lambda c: [len(r['long_frames']) for r in meas if r['app'] == c]
    summary: dict = {"work": str(work)}
    for k in ('title_s', 'title_wait_s', 'rss_max_mb'):
        summary[k] = {c: col(c, k) for c in 'AB'}
        summary[f'{k}_beyond_noise'] = archive.beyond_noise(col('A', k), col('B', k)) if len(col('A', k)) > 1 and len(col('B', k)) > 1 else None
    summary['long_frames'] = {c: nlong(c) for c in 'AB'}
    summary['long_frames_beyond_noise'] = archive.beyond_noise(nlong('A'), nlong('B')) if a.runs > 1 else None
    summary['opens'] = {c: [r['opens'] for r in meas if r['app'] == c] for c in 'AB'}
    summary['gpu_p50_median'] = {c: statistics.median([v for r in meas if r['app'] == c for v in r['gpu_p50']] or [0]) for c in 'AB'}
    summary['b_session_line'] = all(r['m4_session'] for r in meas if r['app'] == 'B')
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('gen', 'ipad'):
        p = sub.add_parser(name)
        p.add_argument('--exe', type=Path, required=True); p.add_argument('--res', type=Path, required=True)
        p.add_argument('--lists', type=Path, nargs='*'); p.add_argument('--out', type=Path, required=True)
        p.add_argument('--work', type=Path)
        if name == 'gen': p.add_argument('--reps', type=int, default=3)
        else: p.add_argument('--seed', type=Path, required=True)
    g = sub.add_parser('game')
    g.add_argument('--app-a', type=Path, required=True); g.add_argument('--app-b', type=Path, required=True)
    g.add_argument('--runs', type=int, default=3); g.add_argument('--play-s', type=float, default=120)
    g.add_argument('--out', type=Path, required=True); g.add_argument('--work', type=Path)
    a = ap.parse_args()
    print(json.dumps({'gen': cmd_gen, 'ipad': cmd_ipad, 'game': cmd_game}[a.cmd](a)))


if __name__ == '__main__':
    sys.exit(main())
