"""BotW 1.9.0 regression A/B: app A (old archive, TOTK_PSO_MTL4=0) against app B (Metal 4, package made from scratch).
Same launch as run.py game (copies of profile/cache/settings, ROUTE, close at play_s), plus a system-wide IOReport
sampler (GPU watts, GPU utilization) running during each launch. Per launch, over the play window
[load started + 20 s, load started + 115 s]: frames per second, frame time percentiles, frames over 16.7 / 33.3 ms,
GPU ms per frame, process CPU per second, pipelines/libraries made in play, GPU watts. Loading: title from the moment the
game data is mounted (excludes the data check, whose record state differs between apps), and load started -> world drawn.
usage: regress.py <app A> <app B> <runs> <out dir> [AB|BA]
The order: AB (2026-11-22, A first in each pair) or BA (B first, to cancel the warming machine's drift).
The sampler: clang -fobjc-arc -O2 sampler.m -o sampler -framework Foundation -framework IOKit -lIOReport (next to this
file). Run under caffeinate -d on AC; the apps' binaries carry test bundle ids (run.py), and launching them registers the
scratch apps with LaunchServices: lsregister -u them and -f the installed app afterwards."""
import json, re, statistics, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'games/totk/tests/mtl4_archive'))
import run

SAMPLER = Path(__file__).resolve().parent / 'sampler'
WIN = (20.0, 115.0)


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))] if v else None


def frames(tsv: Path) -> dict:
    by = {}
    for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines():
        c = line.split('\t')
        if len(c) == 3 and c[1].startswith('@'):
            try:
                by.setdefault(int(c[0]), {})[c[1]] = float(c[2])
            except ValueError:
                pass
    return by


def analyse(out: Path, g: dict, t0: float) -> dict:
    log = [(float(a), b) for a, _, b in (l.partition('\t') for l in (out / 'game.log').read_text(errors='replace').splitlines())
           if a.replace('.', '', 1).isdigit()]
    romfs = next((t for t, s in log if 'native read-only RomFS ready' in s), None)
    verified = any('verifying local RomFS SHA256' in s for t, s in log)
    fr = frames(out / 'frames.tsv')
    ld = g['loaded_s']
    # the frames' clock (@t_s) starts later than the log's (after the game-data check): the offset is log time minus the
    # game time a long-frame line quotes ("帧 N（X s）")
    offs = [t - float(m.group(1)) for t, s in log for m in [re.search(r'\[长帧\] 帧 \d+（([\d.]+) s）', s)] if m]
    off = statistics.median(offs) if offs else 0.0
    # loading: "[world] entered at frame N" (the save's load begins), then a loading screen of a few draws, then the world:
    # the first of 20 frames in a row with 1,000 draws or more after that frame
    wf = next((int(m.group(1)) for t, s in log for m in [re.search(r'\[world\] entered at frame (\d+)', s)] if m), None)
    seq = [f for k, f in sorted(fr.items()) if wf is not None and k > wf]
    world = next((seq[i]['@t_s'] + off for i in range(len(seq) - 20) if all(f.get('@draws', 0) >= 1000 for f in seq[i:i + 20])), None)
    lo, hi = ld + WIN[0], ld + WIN[1]
    w = [f for k, f in sorted(fr.items()) if lo <= f.get('@t_s', -1) + off < hi]
    dur = (w[-1]['@t_s'] - w[0]['@t_s']) if len(w) > 1 else None
    ft = [f['@frame_ms'] for f in w if '@frame_ms' in f]
    pr = [f['@presented_ms'] for f in w if '@presented_ms' in f]
    gp = [f['@gpu_ms'] for f in w if '@gpu_ms' in f]
    s = lambda k: sum(f.get(k, 0) for f in w)
    pw = []
    for line in (out / 'power.tsv').read_text().splitlines()[1:]:
        c = line.split('\t')
        if len(c) == 6 and t0 + lo <= float(c[0]) < t0 + hi:
            pw.append((float(c[1]), float(c[5])))
    return {
        'title_s': g['title_s'], 'title_from_data_s': (g['title_s'] - romfs) if g['title_s'] and romfs else None,
        'data_check_full': verified, 'title_wait_s': g['title_wait_s'],
        'load_to_world_s': (world - ld) if world else None, 'clock_off_s': off,
        'fps': len(w) / dur if dur else None, 'frame_p50': pct(ft, 50), 'frame_p95': pct(ft, 95), 'frame_p99': pct(ft, 99),
        'frame_max': max(ft) if ft else None, 'over_16_7': sum(x > 16.7 for x in ft), 'over_33_3': sum(x > 33.3 for x in ft),
        'presented_p99': pct(pr, 99), 'gpu_ms_p50': pct(gp, 50), 'gpu_ms_p95': pct(gp, 95),
        'gpu_ms_per_s': sum(gp) / dur if dur else None, 'proc_cpu_ms_per_s': s('@proc_cpu_ms') / dur if dur else None,
        'pso_new': s('@pso_new'), 'pso_ms': s('@pso_ms'), 'pso_wait_ms': s('@pso_wait_ms'), 'lib_new': s('@lib_new'),
        'lib_ms': s('@lib_ms'), 'long_frames': len(g['long_frames']),
        'gpu_w': statistics.mean(p[0] for p in pw) if pw else None, 'gpu_util': statistics.mean(p[1] for p in pw) if pw else None,
        'rss_max_mb': g['rss_max_mb'], 'exit': g['exit'], 'killed': g['killed'], 'm4_taken': g['m4_taken'], 'm4_built': g['m4_built'],
    }


def one(app: Path, out: Path, old: bool, cache: Path, play_s: float) -> dict:
    out.mkdir(parents=True)
    p0 = run.pmset()
    with open(out / 'power.tsv', 'w') as f:
        sp = subprocess.Popen([str(SAMPLER), '1'], stdout=f, stderr=subprocess.DEVNULL)
        t0 = time.time()
        try:
            g = run.launch(app, out, old, cache, play_s)
        finally:
            sp.terminate(); sp.wait()
    r = analyse(out, g, t0)
    r.update(power_before=p0, power_after=run.pmset())
    return r


def main():
    app_a, app_b, runs, work = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
    order = sys.argv[5] if len(sys.argv) > 5 else 'AB'
    assert order in ('AB', 'BA'), order
    work.mkdir(parents=True, exist_ok=True)
    apps = {'A': app_a, 'B': app_b}
    src = run.DATA / 'shader-cache/rt-totk-native-v9-unverified'
    prepared, rows = {}, []
    for c in order:
        r = one(apps[c], work / f'prep-{c}', c == 'A', src, 120); r.update(app=c, run='prep'); rows.append(r)
        prepared[c] = work / f'prep-{c}' / 'cache'
        print(json.dumps(r), flush=True)
    for i, c in enumerate(c for _ in range(runs) for c in order):
        r = one(apps[c], work / f'{i}-{c}', c == 'A', prepared[c], 120); r.update(app=c, run=i); rows.append(r)
        print(json.dumps(r), flush=True)
    (work / 'rows.json').write_text(json.dumps(rows, indent=1))


if __name__ == '__main__':
    main()
