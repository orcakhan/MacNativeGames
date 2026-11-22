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


if __name__ == '__main__':
    unittest.main()
