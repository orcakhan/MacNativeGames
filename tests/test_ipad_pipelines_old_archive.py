"""An iPhone / iPad build's pipelines stay in the old archive while the Mac App moves to Metal 4's (2026-11-21,
docs/experiments/2026-11-botw-mtl4-archive). The iPad build never reads the Mac App's files: device_pipelines.make runs the
Mac game binary's pipeline-archive mode itself, from the device seed, and turns the files it writes into the device GPU's
code with metal-tt, which reads their pipeline scripts out of .metalarchive files. That holds only while
- the mode, run without TOTK_PIPELINE_ARCHIVE_HOST, loads the device's libraries (TOTK_SHADER_DEVICE_LIBS=1),
- the Metal 4 archive stays off with them (par4_on), and
- the iPad packaging never asks for the Mac mode.
If any of the three goes, the device build gets .mtl4a files metal-tt cannot read, and its pipelines are left to the
device's first start (Breath of the Wild 1.6.0 on an iPhone 14: 567.8 s before the title)."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
NVN = ROOT / 'games/totk/third_party/d2r_gfx/gfx/nvn'


def body(source, signature):
    start = source.index(signature)
    depth, i = 0, source.index('{', start)
    for j in range(i, len(source)):
        depth += {'{': 1, '}': -1}.get(source[j], 0)
        if not depth:
            return source[i:j + 1]
    raise AssertionError(signature)


class IpadKeepsTheOldArchive(unittest.TestCase):
    def test_device_mode_turns_device_libraries_on(self):
        tool = body((NVN / 'nvn_mtl.m').read_text(encoding='utf-8'), 'int mtl_pipeline_archive_tool(int argc, char **argv)')
        self.assertIn('const char *host = getenv("TOTK_PIPELINE_ARCHIVE_HOST");', tool)
        self.assertIn('if (!(host && !strcmp(host, "1"))) { setenv("TOTK_SHADER_DEVICE_LIBS", "1", 1);', tool)

    def test_metal4_archive_off_with_device_libraries(self):
        on = body((NVN / 'nvn_pso4.h').read_text(encoding='utf-8'), 'static int par4_on(void)')
        self.assertIn('getenv("TOTK_SHADER_DEVICE_LIBS")', on)
        self.assertIn('!(dev && !strcmp(dev, "1"))', on)

    def test_ipad_packaging_never_asks_for_the_mac_mode(self):
        tools = sorted(ROOT.glob('games/*/ios/tools/*.py'))
        self.assertTrue(tools)
        for p in tools:
            self.assertNotIn('TOTK_PIPELINE_ARCHIVE_HOST', p.read_text(encoding='utf-8'), p.relative_to(ROOT))
        dp = (ROOT / 'games/totk/ios/tools/device_pipelines.py').read_text(encoding='utf-8')
        runs = re.findall(r"run\(\[tool, rewritten, 'pipeline-archive'.*", dp)
        self.assertEqual(len(runs), 1)
        self.assertIn('TOTK_SHADER_SEED_DIR=str(seed)', runs[0])


if __name__ == '__main__':
    unittest.main()
