"""The Metal 4 pipeline archive's file-name rules (nvn_pso4_policy.h), run in a compiled probe (no Metal device).

Packaging puts the rows kept before the title into small Metal 4 files of their own (nvn_pso4_build.h g_par4_compact), so
a start reads them before the large files and the next packaging takes them from there. Until 2026-11-21 "small" was
only a count (PAR4_SMALL = 1,024): Breath of the Wild has 1,453 such rows, so its title file never counted as small, every
packaging compiled them again (about 15 s, the capturing compiler uses no cache) and a start opened that file with the
large ones (docs/experiments/2026-11-botw-mtl4-archive). The title periods now carry a mark in their name."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NVN = ROOT / 'games/totk/third_party/d2r_gfx/gfx/nvn'


def body(source, signature):
    start = source.index(signature + ' {')   # the definition, not a forward declaration
    depth, i = 0, source.index('{', start)
    for j in range(i, len(source)):
        depth += {'{': 1, '}': -1}.get(source[j], 0)
        if not depth:
            return source[i:j + 1]
    raise AssertionError(signature)


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('xcrun'), 'requires macOS Foundation')
class Pso4NameRules(unittest.TestCase):
    def test_probe(self):
        with tempfile.TemporaryDirectory() as t:
            binary = Path(t) / 'probe'
            subprocess.run(['xcrun', 'clang', '-fobjc-arc', '-Werror', '-Wall', f'-I{NVN}', str(ROOT / 'tests/pso4_policy_probe.m'),
                            '-framework', 'Foundation', '-o', str(binary)], check=True, capture_output=True, text=True)
            r = subprocess.run([binary], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Pso4UsesTheRules(unittest.TestCase):
    """The archive code takes the rules from the policy header, so the probe tests what packaging and a start do."""
    def setUp(self):
        self.pso4 = (NVN / 'nvn_pso4.h').read_text(encoding='utf-8')
        self.build = (NVN / 'nvn_pso4_build.h').read_text(encoding='utf-8')

    def test_title_periods_are_named_with_the_mark(self):
        self.assertIn('#include "nvn_pso4_policy.h"', self.pso4)
        self.assertNotIn('#define PAR4_SMALL', self.pso4)   # one definition, in the policy header
        publish = body(self.pso4, 'static BOOL par4_publish(Par4Period *p, NSArray<NSString *> *keys, NSError **why)')
        self.assertIn('par4_period_base(keys.firstObject, keys.count, p->title)', publish)
        self.assertIn('p->title = title;', body(self.pso4, 'static Par4Period *par4_new_period(id<MTLDevice> dev, BOOL title)'))
        self.assertIn('par4_new_period(dev, g_par4_compact)', body(self.pso4, 'static Par4Period *par4_enter(id<MTLDevice> dev)'))

    def test_small_means_the_rule_everywhere(self):
        self.assertIn('par4_name_small(', body(self.pso4, 'static void par4_open_all(id<MTLDevice> dev)'))
        self.assertIn('par4_name_small(', body(self.build, 'static int par4_in_small_file(NSString *key)'))
        self.assertNotRegex(self.pso4 + self.build, r'<= PAR4_SMALL')

    def test_a_dropped_or_split_period_keeps_its_title_mark(self):
        # a period the compiler service's death dropped, or a write that failed, is captured again into new periods:
        # they are still the title's rows
        write = body(self.pso4, 'static void par4_write(Par4Period *p)')
        self.assertIn('par4_recapture(keys, descs, 1, p->title)', write)
        self.assertIn('par4_resplit(keys, descs, p->title)', write)
        chunk = body(self.build, 'static void par4_capture_chunk_n(NSArray<NSString *> *k, NSArray *d, int tries, BOOL title)')
        self.assertIn('par4_new_period(g_dev, title)', chunk)
        self.assertIn('par4_recapture(got, gotd, tries + 1, title)', chunk)
        self.assertIn('par4_resplit(got, gotd, title)', chunk)

    def test_packaging_spreads_its_blocks_and_only_packaging(self):
        # the spread and the larger block are for the pipeline-archive mode with the Metal 4 archive (captures wait on
        # each other there); the first-start fill before the title, the old archive, device mode and other games keep
        # the sorted 512-row blocks
        mtl = (NVN / 'nvn_mtl.m').read_text(encoding='utf-8')
        fill = body(mtl, 'static void warm_fill_archive(NSArray<NSString *> *paths, dispatch_semaphore_t done)')
        self.assertIn('NSUInteger rows = todo.count, block_rows = WARM_BLOCK;', fill)   # the default stays 512 sorted rows
        # Breath of the Wild 1.9.0 only, until Ocarina of Time's packaging is measured with it (review 2026-11-21)
        gate = fill.index('#if defined(GAME_BOTW190)')
        on = fill.index('int spread = g_compute_archive_tool && par4_on();')
        self.assertLess(gate, on)
        self.assertNotIn('#endif', fill[gate:on])
        self.assertIn('#ifdef PSO4_BUILT', fill[:gate])
        for line in ('if (spread) block_rows = PAR4_FILL_BLOCK;', 'if (spread) block = par4_spread(block);', 'if (spread) par4_cut_block();'):
            self.assertIn(line, fill)
        self.assertIn('[todo sortUsingSelector:@selector(compare:)]', fill)   # still sorted first: shaders load once per block

    def test_a_spread_block_ends_its_period(self):
        # a Metal 4 file keeps a function's code once; a period cut inside a spread block put most of that block's vertex
        # shaders into two files (Breath of the Wild: 485 MB instead of 460). A block's end writes the period when it holds
        # half a period or more; a rebuild's few stale rows stay in the open period instead of making small files
        cut = body((NVN / 'nvn_pso4.h').read_text(encoding='utf-8'), 'static void par4_cut_block(void)')
        self.assertIn('p->captured >= PAR4_PERIOD_MAX / 2', cut)
        self.assertIn('g_par4_period = nil;', cut)
        self.assertIn('par4_write(p)', cut)


if __name__ == '__main__':
    unittest.main()
