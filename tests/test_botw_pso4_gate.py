"""The Metal 4 pipeline archive (nvn_pso4*.h) runs for Ocarina of Time and Breath of the Wild 1.9.0 on the Mac only
(2026-11-21, docs/experiments/2026-11-botw-mtl4-archive). Elsewhere it must stay off:
- iPhone, iPad and Vision Pro have no Metal 4 pipeline path (TARGET_OS_IPHONE is 1 on visionOS too);
- Tears of the Kingdom and Breath of the Wild 1.6.0 are not measured yet: their App keeps the old archive.
And Breath of the Wild 1.9.0 writes the period it is still capturing when its window closes (mtl_pipeline_archive_quit), as
Ocarina of Time does; without it the last pipelines compiled in play are lost and the session line is never printed.
Tears of the Kingdom must not call it: it would add a wait on pso_user_queue to every close (nvn_mtl.m)."""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
NVN = ROOT / 'games/totk/third_party/d2r_gfx/gfx/nvn'
FRONT = ROOT / 'games/totk/runtime/frontend.m'


def built(sdk, triple, defines):
    """Whether nvn_pso4_fn.h defines PSO4_BUILT for this SDK, target and game macros. A missing SDK fails the test."""
    r = subprocess.run(['xcrun', '-sdk', sdk, 'clang', '-E', '-dM', '-x', 'objective-c', '-target', triple, *defines,
                        f'-I{NVN}', str(NVN / 'nvn_pso4_fn.h')], capture_output=True, text=True, errors='replace')
    if r.returncode:
        raise AssertionError(f'{sdk} {triple}: {r.stderr[-1500:]}')
    return re.search(r'^#define PSO4_BUILT 1$', r.stdout, re.M) is not None


MAC = ('macosx', 'arm64-apple-macos14')
BOTW190 = ['-DGAME_BOTW=1', '-DGAME_BOTW190=1']


class Gate(unittest.TestCase):
    def test_metal4_archive_on_for_oot_and_botw190_on_the_mac(self):
        self.assertTrue(built(*MAC, ['-DGAME_OOT=1']))
        self.assertTrue(built(*MAC, BOTW190))

    def test_off_for_totk_and_botw160(self):
        self.assertFalse(built(*MAC, []))
        self.assertFalse(built(*MAC, ['-DTOTK_GAME_V143=1']))
        self.assertFalse(built(*MAC, ['-DGAME_BOTW=1', '-DGAME_BOTW160=1']))

    def test_off_on_iphone_ipad_and_vision_pro(self):
        for sdk, triple in (('iphoneos', 'arm64-apple-ios17.0'), ('xros', 'arm64-apple-xros2.0')):
            for d in (BOTW190, ['-DGAME_OOT=1']):
                self.assertFalse(built(sdk, triple, d), (sdk, d))


def botw190_blocks(text):
    """The text of every '#ifdef GAME_BOTW190' ... '#endif' block (no nesting in frontend.m)."""
    return re.findall(r'^#ifdef GAME_BOTW190\b.*?\n(.*?)^#endif', text, re.M | re.S)


class WindowClose(unittest.TestCase):
    def setUp(self):
        self.text = FRONT.read_text(encoding='utf-8')
        start = self.text.index('-(void)windowWillClose:')
        self.close = self.text[start:self.text.index('\n-(', start + 1)]

    def test_botw190_writes_the_last_period_before_exit(self):
        call = 'if(mtl_pipeline_archive_quit)mtl_pipeline_archive_quit();'
        self.assertIn(call, self.close)
        self.assertLess(self.close.index(call), self.close.index('if(!runtime_fs_save_busy())'))
        self.assertTrue(any(call in b and b.strip().count('\n') <= 1 for b in botw190_blocks(self.close)),
                        'the call must sit alone in an #ifdef GAME_BOTW190 block')
        self.assertTrue(any('__attribute__((weak)) void mtl_pipeline_archive_quit(void);' in b for b in botw190_blocks(self.text)),
                        'the weak declaration must be BotW 1.9.0 only too')

    def test_totk_does_not_call_it(self):
        outside = self.text
        for b in botw190_blocks(self.text):
            outside = outside.replace(b, '')
        self.assertNotIn('mtl_pipeline_archive_quit', outside)


if __name__ == '__main__':
    unittest.main()
