"""Recompute regress.py's per-launch numbers from the saved files (game.log, frames.tsv, power.tsv), with the corrected
analysis. t0 (launch start, epoch) is taken as the sampler's first line minus its 1 s interval (it starts just before
the launch). exit/killed come from regress.out's rows. Then the per-arm summary: values, medians, and B - A in %.
usage: reanalyse.py <work dir> <regress.out>"""
import json, statistics, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'games/totk/tests/mtl4_archive'))
import archive, regress

work, outf = Path(sys.argv[1]), Path(sys.argv[2])
printed = {}
for l in outf.read_text().splitlines():
    if l.startswith('{'):
        d = json.loads(l); printed[(d['app'], str(d['run']))] = d
rows = []
for d in sorted(work.iterdir()):
    if not (d / 'frames.tsv').is_file():
        continue
    run_, app = d.name.split('-')
    lines = []
    for l in (d / 'game.log').read_text(errors='replace').splitlines():
        t, _, s = l.partition('\t')
        try:
            lines.append((float(t), s))
        except ValueError:
            pass
    g = archive.parse_game(lines)
    p = printed.get((app, run_), {})
    g.update(loaded_s=next(t for t, s in lines if '[autoload] load started' in s), killed=p.get('killed'), exit=p.get('exit'))
    pw = (d / 'power.tsv').read_text().splitlines()
    t0 = float(pw[1].split('\t')[0]) - 1.0
    r = regress.analyse(d, g, t0); r.update(app=app, run=run_, power_before=p.get('power_before'), power_after=p.get('power_after'))
    rows.append(r)
(work / 'rows-reanalysed.json').write_text(json.dumps(rows, indent=1))

meas = [r for r in rows if r['run'] != 'prep']
keys = ['title_from_data_s', 'title_s', 'load_to_world_s', 'fps', 'frame_p50', 'frame_p95', 'frame_p99', 'frame_max',
        'over_16_7', 'over_33_3', 'presented_p99', 'gpu_ms_p50', 'gpu_ms_p95', 'gpu_ms_per_s', 'proc_cpu_ms_per_s',
        'gpu_w', 'gpu_util', 'pso_new', 'pso_ms', 'lib_new', 'long_frames', 'rss_max_mb']
print(f"{'metric':20} {'A (old)':>34} {'B (Metal 4)':>34} {'B-A %':>7}")
for k in keys:
    a = [r[k] for r in meas if r['app'] == 'A' and r[k] is not None]
    b = [r[k] for r in meas if r['app'] == 'B' and r[k] is not None]
    if not a or not b:
        print(k, a, b); continue
    ma, mb = statistics.median(a), statistics.median(b)
    f = lambda v: ' '.join(f'{x:.2f}' if isinstance(x, float) else str(x) for x in v)
    print(f"{k:20} {f(a):>34} {f(b):>34} {((mb - ma) / ma * 100 if ma else 0):>+7.1f}")
print('exits', [(r['app'], r['run'], r['exit'], r['killed'], r['data_check_full'], round(r['clock_off_s'], 2)) for r in rows])
print('B session', [(r['run'], r['m4_taken'], r['m4_built']) for r in rows if r['app'] == 'B'])
print('power', [(r['app'], r['run'], (r['power_before'] or '')[-30:], (r['power_after'] or '')[-30:]) for r in rows])
