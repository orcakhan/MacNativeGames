"""Per-frame cost fields, median over each launch's play window, paired B vs A within each pair of both rounds
(round 1 <dir>/runs-regress: A first; round 2 <dir>/runs-regress-ba: B first; writes <dir>/power/perframe.json).
usage: perframe.py <dir>"""
import sys, json, re, statistics
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import regress

M = Path(sys.argv[1])
F = ['@frame_ms', '@work_ms', '@nvn_ms', '@cpu_ms', '@sub_cpu_ms', '@sub_wall_ms', '@gpu_ms', '@draws', '@passes',
     '@core_wait_all_ms', '@args_enc', '@cbc_miss', '@faults', '@mprotect_ms', '@xl_sync_ms', '@wait_ms', '@pq_wait_ms',
     '@svc_ms', '@sub_instr', '@proc_cpu_ms']


def one(d):
    log = []
    for l in (d / 'game.log').read_text(errors='replace').splitlines():
        t, _, s = l.partition('\t')
        try:
            log.append((float(t), s))
        except ValueError:
            pass
    ld = next(t for t, s in log if '[autoload] load started' in s)
    offs = [t - float(m.group(1)) for t, s in log for m in [re.search(r'\[长帧\] 帧 \d+（([\d.]+) s）', s)] if m]
    off = statistics.median(offs)
    fr = regress.frames(d / 'frames.tsv')
    w = [f for f in fr.values() if ld + 20 <= f.get('@t_s', -1) + off < ld + 115]
    r = {k: statistics.median([f.get(k, 0) for f in w]) for k in F}
    r['fps'] = len(w) / 95
    return r


rows = []
for rnd, name in ((1, 'runs-regress'), (2, 'runs-regress-ba')):
    for d in (M / name).iterdir():
        if not (d / 'frames.tsv').is_file() or d.name.startswith('prep'):
            continue
        i, app = d.name.split('-')
        r = one(d); r.update(rnd=rnd, i=int(i), app=app); rows.append(r)
(M / 'power/perframe.json').write_text(json.dumps(rows))
print(f"{'field':18} {'mean B-A %':>10}  r1 pairs (A first) | r2 pairs (B first)")
for k in ['fps'] + F:
    ds = []
    for rnd in (1, 2):
        rr = sorted([r for r in rows if r['rnd'] == rnd], key=lambda r: r['i'])
        for j in range(0, 8, 2):
            a = [r for r in rr[j:j + 2] if r['app'] == 'A'][0]; b = [r for r in rr[j:j + 2] if r['app'] == 'B'][0]
            ds.append((b[k] - a[k]) / a[k] * 100 if a[k] else 0)
    print(f"{k:18} {statistics.mean(ds):>+10.2f}  {' '.join(f'{x:+.1f}' for x in ds[:4])} | {' '.join(f'{x:+.1f}' for x in ds[4:])}")
