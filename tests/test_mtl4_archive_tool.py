"""Phase 0 of Breath of the Wild 1.9.0's Metal 4 pipeline archive on the Mac (docs/experiments/2026-11-botw-mtl4-archive,
games/totk/tests/mtl4_archive): the rules its numbers are decided on. Coverage counted from what was written instead of
what a second process finds, a compile on that check run let through, a run whose Metal 4 line is missing read as zero,
a long frame of exactly 100 ms left out, or a gain inside the noise read as one would each turn a stop into a go (or back).
A run under the games' bundle id would write into the installed games' Metal cache, which the user ruled out."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'games/totk/tests/mtl4_archive'
sys.path.insert(0, str(TOOL))
import archive  # noqa: E402

FIX = TOOL / 'fixtures'


class Tool(unittest.TestCase):
    def test_parse_tool_reads_the_metal4_line_and_the_report(self):
        r = archive.parse_tool((FIX / 'tool.log').read_text(encoding='utf-8'), expect_m4=True)
        self.assertEqual((r['m4_hits'], r['m4_built'], r['m4_files'], r['m4_written'], r['old_path'], r['gave_up']),
                         (17000, 712, 9, 712, 183, 2))
        self.assertEqual(r['report']['render'], 17712)
        self.assertEqual(r['report']['arch'], 'applegpu_g17s')
        self.assertEqual(r['red'], 1)

    def test_missing_metal4_line_is_loud(self):
        text = ''.join(l for l in (FIX / 'tool.log').read_text(encoding='utf-8').splitlines(True) if '取 ' not in l)
        with self.assertRaises(ValueError):
            archive.parse_tool(text, expect_m4=True)
        self.assertIsNone(archive.parse_tool(text, expect_m4=False)['m4_hits'])   # the old arm prints none

    def test_missing_report_is_loud(self):
        with self.assertRaises(ValueError):
            archive.parse_tool('[dm] nothing\n', expect_m4=False)


class Coverage(unittest.TestCase):
    def test_coverage_is_what_a_second_process_finds(self):
        c = archive.coverage({'m4_hits': 17000, 'm4_built': 0}, 17897)
        self.assertAlmostEqual(c['pct'], 94.988, places=2)
        self.assertTrue(c['ok'])

    def test_a_compile_on_the_check_run_fails_coverage(self):
        # a pipeline the Metal 4 file should hold that the check run compiles again: written, never found
        self.assertFalse(archive.coverage({'m4_hits': 17897, 'm4_built': 3}, 17897)['ok'])
        self.assertFalse(archive.coverage({'m4_hits': 17897, 'm4_built': 1456, 'compact_built': 1453}, 17897)['ok'])

    def test_the_title_file_pass_is_not_a_miss(self):
        # packaging first compiles the rows kept before the title into a small file of their own (nvn_mtl.m
        # g_par4_compact); BotW's 1,453 are more than PAR4_SMALL (1,024), so every packaging, the check run included,
        # compiles them again (2026-11-21): that pass is counted apart, not as a miss
        c = archive.coverage({'m4_hits': 18249, 'm4_built': 1453, 'compact_built': 1453}, 18250)
        self.assertTrue(c['ok'])
        self.assertEqual((c['misses'], c['title_pass']), (0, 1453))
        text = '[dm] [nvn-mtl] Metal 4 管线存档：标题前常驻的 1469 行放进小文件（新编 1453 条，14.5 s）\n' + (FIX / 'tool.log').read_text(encoding='utf-8')
        self.assertEqual(archive.parse_tool(text, expect_m4=True)['compact_built'], 1453)
        self.assertEqual(archive.parse_tool((FIX / 'tool.log').read_text(encoding='utf-8'), expect_m4=True)['compact_built'], 0)


class Package(unittest.TestCase):
    def test_package_counts_what_the_app_carries(self):
        with tempfile.TemporaryDirectory() as t:
            made = Path(t) / 'cache/pipelines'; made.mkdir(parents=True)
            m4 = made.parent / 'pipelines-mtl4'; m4.mkdir()
            (made / 'aa.metalarchive').write_bytes(b'x' * 100); (made / 'aa.keys').write_text('k1\nk2\n')
            (made / 'bb.metalarchive').write_bytes(b'y' * 50); (made / 'bb.keys').write_text('k3\n')
            (m4 / 'k3-2.mtl4a').write_bytes(b'z' * 30); (m4 / 'k3-2.keys').write_text('k3\nk4\n')
            os.utime(made / 'aa.keys', (1000, 1000)); os.utime(made / 'bb.keys', (1000, 1000)); os.utime(m4 / 'k3-2.keys', (2000, 2000))
            p = archive.package(made, 'applegpu_g17s', 'chain')
        # bb's only key went to the newer Metal 4 file, so the App does not carry bb
        self.assertEqual((p['keys'], p['old_files'], p['old_bytes'], p['mtl4a_files'], p['mtl4a_bytes']), (4, 1, 100, 1, 30))
        self.assertEqual((p['files'], p['bytes']), (2, 130))


class Game(unittest.TestCase):
    def setUp(self):
        lines = (FIX / 'game.log').read_text(encoding='utf-8').splitlines()
        self.g = archive.parse_game([(10.0 + i, l) for i, l in enumerate(lines)])

    def test_title_and_its_wait(self):
        self.assertEqual(self.g['title_s'], 10.0)
        self.assertEqual(self.g['title_wait_s'], 1.9)

    def test_long_frame_threshold(self):
        self.assertEqual([f['ms'] for f in self.g['long_frames']], [182.7])   # 85.5 ms is not long
        edge = archive.parse_game([(0.0, '[totk-gfx] [长帧] 帧 1（1.00 s）整帧 100.0 ms，提交+出图 1.0 ms'),
                                   (0.1, '[totk-gfx] [长帧] 帧 2（1.10 s）整帧 99.9 ms，提交+出图 1.0 ms')])
        self.assertEqual([f['ms'] for f in edge['long_frames']], [100.0])

    def test_memory_gpu_and_session_line(self):
        self.assertEqual(self.g['rss_max_mb'], 2504)
        self.assertEqual(self.g['gpu_p50'], [2.73, 4.33])
        self.assertFalse(self.g['m4_session'])
        s = archive.parse_game([(1.0, '[dm] [nvn-mtl] Metal 4 管线存档（这一局）：取 5 条，编 0 条')])
        self.assertTrue(s['m4_session'])

    def test_tsv_opens(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / 'run.tsv'
            f.write_text('# kind\nframe\tname\tvalue\n1\t@par_opens\t2.000\n1\t@par_open_ms\t3.500\n2\t@par_opens\t1.000\n2\t@other\t9\n')
            self.assertEqual(archive.parse_tsv_opens(f), {'opens': 3, 'open_ms': 3.5})


class Noise(unittest.TestCase):
    def test_beyond_noise(self):
        self.assertFalse(archive.beyond_noise([10.0] * 6, [10.0] * 6))
        self.assertTrue(archive.beyond_noise([10.0, 10.1] * 3, [9.0, 9.1] * 3))       # faster, past the noise, 10%
        self.assertFalse(archive.beyond_noise([10.0, 14.0] * 3, [9.0, 13.0] * 3))     # inside the noise
        self.assertFalse(archive.beyond_noise([10.0, 10.01] * 3, [9.8, 9.81] * 3))    # past the noise, only 2%
        self.assertFalse(archive.beyond_noise([9.0, 9.1] * 3, [10.0, 10.1] * 3))      # slower is no gain


class BundleId(unittest.TestCase):
    def test_bundle_id_same_length(self):
        blob = b'aa<string>org.macnativegames.mtl4test-0000</string>bb'
        out = archive.with_bundle_id(blob, 7)
        self.assertEqual(len(out), len(blob))
        self.assertIn(b'<string>org.macnativegames.mtl4test-0007</string>', out)
        with self.assertRaises(ValueError):
            archive.with_bundle_id(b'<string>org.macnativegames.totk-native</string>', 7)   # the games' id is never renamed into


class Runner(unittest.TestCase):
    def test_arms_alternate_which_goes_first(self):
        import run
        self.assertEqual(run.arm_order(3), [('old', 'new'), ('new', 'old'), ('old', 'new')])
        self.assertEqual(''.join(run.game_order(3)), 'ABABAB')

    def test_tool_env_mirrors_packaging_and_lets_a_run_override_it(self):
        # the check run looks every key up again (TOTK_PAR_RECHECK=1) where a plain run does not; the game's own TOTK_ / DM_
        # settings of the shell never leak in
        import run
        os.environ['TOTK_PSO_MTL4'] = '0'
        try:
            env = run.tool_env(Path('/r'), Path('/f'), None, True, {'TOTK_PAR_RECHECK': '1'})
        finally:
            del os.environ['TOTK_PSO_MTL4']
        self.assertEqual(env['TOTK_PAR_RECHECK'], '1')
        self.assertEqual((env['TOTK_SHADER_CACHE'], env['TOTK_SHADER_SEED_DIR'], env['TOTK_PIPELINE_ARCHIVE_HOST']),
                         ('/f', '/r/build/shader-seed', '1'))
        self.assertNotIn('TOTK_PSO_MTL4', env)
        device = run.tool_env(Path('/r'), Path('/f'), Path('/seed'), False, {})
        self.assertNotIn('TOTK_PIPELINE_ARCHIVE_HOST', device)
        self.assertEqual((device['TOTK_PAR_RECHECK'], device['TOTK_SHADER_SEED_DIR']), ('0', '/seed'))

    def test_a_run_must_load_the_apps_compiled_libraries(self):
        # run from anywhere but the app's build folder, the binary finds no shader-libs beside it (nvn_mtl.m exe_rel) and
        # compiles every shader from source (2026-11-21: 8,401 of them): every pipeline then comes from a runtime library,
        # and both time and coverage are wrong
        import run
        res = Path('/app/Contents/Resources/totk')
        run.check_libs({'libs': '/app/Contents/Resources/totk/build/shader-libs'}, res)
        for bad in ('', '/elsewhere/shader-libs'):
            with self.assertRaises(ValueError):
                run.check_libs({'libs': bad}, res)

    def test_drop_cache_removes_only_a_test_bundle_ids_folder(self):
        import run
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            for name in ('org.macnativegames.totk-native', 'org.macnativegames.mtl4test-0007', 'org.macnativegames.mtl4test-0008'):
                (root / name / 'com.apple.metal').mkdir(parents=True)
            run.drop_cache(7, root)
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             ['org.macnativegames.mtl4test-0008', 'org.macnativegames.totk-native'])
            for bad in (-1, 10000):
                with self.assertRaises(ValueError):
                    run.drop_cache(bad, root)


class Leftover(unittest.TestCase):
    def test_leftover_classes(self):
        p = json.loads((FIX / 'pipelines.json').read_text())
        libs = {'FIXTURE': Path('/x/fixture.metallib')}
        self.assertEqual(archive.leftover_class(p['shader_lib'], libs), 'other')
        self.assertEqual(archive.leftover_class(p['runtime_lib'], libs), 'runtime library')
        self.assertEqual(archive.leftover_class(p['depth_only'], libs), 'depth only')
        self.assertEqual(archive.leftover_class(p['compute'], libs), 'other')
        self.assertEqual(archive.leftover_class({**p['compute'], 'compute_function': 'alias:MISSING#main0'}, libs), 'runtime library')
        self.assertEqual(archive.leftover_class(p['shader_lib'], libs, mesh=True), 'mesh')


if __name__ == '__main__':
    unittest.main()
