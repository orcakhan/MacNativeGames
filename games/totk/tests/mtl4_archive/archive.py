#!/usr/bin/env python3
"""Phase 0 of Breath of the Wild 1.9.0's Metal 4 pipeline archive on the Mac (docs/experiments/2026-11-botw-mtl4-archive;
the design: the old MTLBinaryArchive, 8 pipelines a file, moved to Metal 4's archive, up to 2,000 a file, by the path
Ocarina of Time uses, nvn_pso4*.h). The rules the numbers are read with; run.py runs the tool and the game.

- parse_tool: what the game binary's pipeline-archive mode reports (its last JSON line, and on the Mac with Metal 4 on the
  line nvn_mtl.m prints after the fill: 取 hits / 编 built / files / written / 走旧路 old path / 让出 gave up).
- coverage: the share of keys a SECOND process found in the Metal 4 files (a check run with TOTK_PAR_RECHECK=1, which looks
  every listed key up); any pipeline that run compiled was written but not found.
- package: what the App would carry, through build_app.mac_pipeline_files itself.
- parse_game / parse_tsv_opens: one launch's title time, long frames (100 ms or more), memory, GPU p50 and archive opens.
- beyond_noise: a gain counts only past 2 pooled standard deviations and by 5% or more.
- with_bundle_id: Metal keeps compiled code per bundle id; every run here uses org.macnativegames.mtl4test-NNNN, never the
  games' org.macnativegames.totk-native."""
import json
import re
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TEST_ID = b'<string>org.macnativegames.mtl4test-0000</string>'
M4_LINE = re.compile(r'Metal 4 管线存档：取 (\d+) 条、编 (\d+) 条（写进 (\d+) 个文件 (\d+) 条），走旧路 (\d+) 条，捕获时让出 (\d+) 次')


def with_bundle_id(blob: bytes, n: int) -> bytes:
    if blob.count(TEST_ID) != 1:
        raise ValueError('no org.macnativegames.mtl4test-0000 bundle id to replace')
    return blob.replace(TEST_ID, f'<string>org.macnativegames.mtl4test-{n:04d}</string>'.encode())


def parse_tool(text: str, expect_m4: bool) -> dict:
    report = None
    for line in text.splitlines():
        if line.startswith('{'):
            try:
                report = json.loads(line)
            except ValueError:
                pass
    if not isinstance(report, dict) or 'render' not in report:
        raise ValueError('no report line from the pipeline-archive mode')
    m = M4_LINE.findall(text)
    if expect_m4 and not m:
        raise ValueError('no Metal 4 archive line: was the binary built with PSO4_BUILT and the archive on?')
    vals = [int(x) for x in m[-1]] if m else [None] * 6
    out: dict = dict(zip(('m4_hits', 'm4_built', 'm4_files', 'm4_written', 'old_path', 'gave_up'), vals))
    out['report'] = report
    out['red'] = sum('【红】' in line for line in text.splitlines())
    return out


def coverage(check: dict, keys_total: int) -> dict:
    return {'pct': 100 * check['m4_hits'] / keys_total, 'built_on_check': check['m4_built'], 'ok': check['m4_built'] == 0}


def package(made: Path, arch: str, chain: str) -> dict:
    sys.path.insert(0, str(ROOT))
    import build_app
    with tempfile.TemporaryDirectory() as t:
        seed = Path(t) / 'seed'
        keys = build_app.mac_pipeline_files(Path(made), seed, arch, chain)
        files = [p for p in seed.iterdir() if p.suffix in ('.metalarchive', '.mtl4a')]
        old = [p for p in files if p.suffix == '.metalarchive']
        m4 = [p for p in files if p.suffix == '.mtl4a']
        size = lambda ps: sum(p.stat().st_size for p in ps)
        return {'keys': keys, 'files': len(files), 'bytes': size(files), 'old_files': len(old), 'old_bytes': size(old),
                'mtl4a_files': len(m4), 'mtl4a_bytes': size(m4)}


def _labels(p):
    for f in ('vertex_function', 'fragment_function', 'compute_function'):
        v = p.get(f)
        if v is None:
            continue
        if not v.startswith('alias:') or '#' not in v:
            yield None
        else:
            yield v[len('alias:'):v.index('#')].upper()


def leftover_class(pipeline: dict, libs: dict, mesh: bool = False) -> str:
    """Why a pipeline left in the old archive is there, from its pipeline script (metal-source --extract=metal-scripts):
    a mesh pipeline (the script's mesh list: Metal 4 is not tried for them); rasterization without a fragment function
    (Metal 4 needs one, nvn_pso4_build.h pso4_desc); a function from a library the App's shader-libs do not hold (compiled
    at run time: border, tile read, retyped outputs); else 'other'."""
    if mesh:
        return 'mesh'
    if 'compute_function' not in pipeline and pipeline.get('rasterization_enabled', True) and not pipeline.get('fragment_function'):
        return 'depth only'
    if any(l is None or l not in {k.upper() for k in libs} for l in _labels(pipeline)):
        return 'runtime library'
    return 'other'


LONG = re.compile(r'\[长帧\] 帧 (\d+)（[\d.]+ s）整帧 ([\d.]+) ms，(.*)')
TITLE = re.compile(r'预热和管线存档完成后才进标题：又等了 ([\d.]+) s')
RSS = re.compile(r'内存 至帧 \d+：常驻 (\d+) MB')
GPU = re.compile(r'计时 至帧 \d+：.*GPU p50 ([\d.]+)')


def parse_game(lines) -> dict:
    """lines: (seconds since launch, text). Long frames are 100 ms or more (the user's threshold), with their cause."""
    out = {'title_s': None, 'title_wait_s': None, 'long_frames': [], 'rss_max_mb': None, 'gpu_p50': [], 'm4_session': False}
    for t, line in lines:
        m = TITLE.search(line)
        if m and out['title_s'] is None:
            out['title_s'], out['title_wait_s'] = t, float(m.group(1))
        m = LONG.search(line)
        if m and float(m.group(2)) >= 100.0:
            out['long_frames'].append({'frame': int(m.group(1)), 'ms': float(m.group(2)), 'at_s': t, 'cause': m.group(3)})
        m = RSS.search(line)
        if m:
            out['rss_max_mb'] = max(out['rss_max_mb'] or 0, int(m.group(1)))
        m = GPU.search(line)
        if m:
            out['gpu_p50'].append(float(m.group(1)))
        if 'Metal 4 管线存档（这一局）' in line:
            out['m4_session'] = True
    return out


def parse_tsv_opens(path: Path) -> dict:
    opens, ms = 0.0, 0.0
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        c = line.split('\t')
        if len(c) == 3 and c[1] == '@par_opens':
            opens += float(c[2])
        elif len(c) == 3 and c[1] == '@par_open_ms':
            ms += float(c[2])
    return {'opens': int(round(opens)), 'open_ms': ms}


def beyond_noise(a, b, min_pct: float = 5.0) -> bool:
    """b (new) lower than a (old) by more than 2 pooled standard deviations and by min_pct % of mean(a) or more."""
    gain = statistics.mean(a) - statistics.mean(b)
    pooled = ((statistics.variance(a) + statistics.variance(b)) / 2) ** 0.5
    return gain > 2 * pooled and gain >= min_pct / 100 * statistics.mean(a)
