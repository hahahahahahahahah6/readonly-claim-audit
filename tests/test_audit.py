import contextlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest

from readonly_claim_audit import audit, claims_in, main, HIGH_RULE, TEST_RULE


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.put('README.md', 'This tool is read-only.\n')

    def put(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = main([str(self.root), *args])
            except SystemExit as error:
                code = error.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_good(self):
        self.put('src/app.py', 'open("data", "r")\np.read_text()\njson.load(stream)\n')
        code, out, _ = self.cli('--json')
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)['verified_claims']), 1)
        self.assertIn('VERIFIED', self.cli('--verbose')[1])

    def test_bad_and_guard(self):
        self.put('src/app.py', 'Path("out").write_text("data")\n')
        marker = 'ENV_GUARD_NEVER_EMITTED_123'
        self.put('.env', marker)
        for options in [(), ('--json',), ('--verbose',)]:
            code, out, err = self.cli(*options)
            self.assertEqual(code, 2)
            self.assertNotIn(marker, out + err)
        result = json.loads(self.cli('--json')[1])
        self.assertEqual(len(result['findings']), 1)
        finding = result['findings'][0]
        self.assertEqual((finding['rule'], finding['severity'], finding['file'], finding['line']), (HIGH_RULE, 'HIGH', 'src/app.py', 1))

    def test_test_only(self):
        self.put('tests/test_app.py', 'p.write_bytes(b"x")')
        code, out, _ = self.cli('--json')
        self.assertEqual(code, 2)
        finding = json.loads(out)['findings']
        self.assertEqual(len(finding), 1)
        self.assertEqual((finding[0]['rule'], finding[0]['severity']), (TEST_RULE, 'MEDIUM'))
        code, out, _ = self.cli('--fail-on', 'HIGH')
        self.assertEqual(code, 0)
        self.assertIn('MEDIUM ' + TEST_RULE, out)

    def test_variable_mode(self):
        self.put('app.py', 'mode = "w"\nopen(p, mode)\nio.open(p, mode=mode)')
        self.assertEqual(audit(self.root)['status'], 'PASS')

    def test_fences(self):
        for fence in ['```', '~~~~']:
            self.put('README.md', fence + 'python\nread-only\n' + fence + '\n')
            self.put('app.py', 'p.write_text("x")')
            self.assertEqual(audit(self.root)['findings'], [])

    def test_no_claim(self):
        self.put('README.md', 'Writes a report to out/.')
        self.put('app.py', 'p.write_text("x")')
        self.assertEqual(audit(self.root)['status'], 'PASS')

    def test_open_mode_matrix(self):
        for call in ['open', 'io.open']:
            for mode in ['w', 'a', 'x', 'wb', 'r+', 'r', 'rb']:
                for keyword in [False, True]:
                    with self.subTest(call=call, mode=mode, keyword=keyword):
                        self.put('app.py', '{}(p, {}{!r})'.format(call, 'mode=' if keyword else '', mode))
                        self.assertEqual(len(audit(self.root)['findings']), int(mode not in ['r', 'rb']))
        self.put('app.py', 'open(p)\nio.open(p)')
        self.assertEqual(audit(self.root)['findings'], [])

    def test_ignore(self):
        self.put('app.py', 'p.write_text("x")')
        self.assertEqual(self.cli('--ignore', HIGH_RULE)[0], 0)
        self.assertEqual(json.loads(self.cli('--ignore', HIGH_RULE, '--json')[1])['findings'], [])

    def test_version_and_errors(self):
        self.assertEqual(self.cli('--version')[:2], (0, '0.1.0\n'))
        self.assertEqual(self.cli('--fail-on', 'LOW')[0], 1)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(self.root / 'missing')]), 1)
        self.put('app.py', 'invalid syntax !!!')
        self.assertEqual(self.cli()[0], 1)

    def test_no_source_one_per_claim(self):
        self.put('README.md', 'Read-only and never writes.\n')
        findings = audit(self.root)['findings']
        self.assertEqual(len(findings), 2)
        self.assertTrue(all(f['severity'] == 'HIGH' for f in findings))

    def test_all_patterns_and_dedup(self):
        phrases = ['read-only', 'read only', 'does not modify', "doesn't modify", 'never modifies', 'never modify', 'does not write', "doesn't write", 'never writes', 'never write', 'no writes', 'does not change', 'never changes']
        for phrase in phrases:
            self.assertEqual(len(list(claims_in(phrase.upper(), 'README.md'))), 1)
        self.put('app.py', 'p.write_text("a"); p.write_bytes(b"b")\np.write_text("c")')
        self.assertEqual(len(audit(self.root)['findings']), 2)

    def test_evidence_table(self):
        calls = ['os.' + name for name in ['remove', 'unlink', 'rename', 'replace', 'mkdir', 'makedirs', 'rmdir', 'removedirs']]
        calls += ['shutil.' + name for name in ['copy', 'copy2', 'move', 'rmtree']]
        calls += ['p.write_text', 'p.write_bytes']
        self.put('app.py', '\n'.join(call + '(p)' for call in calls))
        self.assertEqual(len(audit(self.root)['findings']), len(calls))
        self.put('app.py', 'os.chmod(p, 0)\nos.utime(p)\nprint("x", file=stream)')
        self.assertEqual(audit(self.root)['findings'], [])

    def test_test_path_matrix_and_mixed(self):
        for name in ['tests/a.py', 'fixtures/a.py', 'test_a.py', 'a_test.py']:
            path = self.put(name, 'p.write_text("x")')
            self.assertEqual(audit(self.root)['findings'][0]['rule'], TEST_RULE)
            path.unlink()
        self.put('tests/a.py', 'p.write_text("x")')
        self.put('app.py', 'p.write_text("x")')
        self.assertEqual([f['rule'] for f in audit(self.root)['findings']], [HIGH_RULE])

    def test_docs_and_symlinks(self):
        self.put('README.md', 'Overview')
        self.put('docs/nested/guide.md', 'Never writes files.')
        self.put('app.py', 'p.read_text()')
        outside = self.put('outside.txt', 'p.write_text("x")')
        (self.root / 'linked.py').symlink_to(outside)
        (self.root / 'docs/link.md').symlink_to(outside)
        (self.root / 'linked_dir').symlink_to(self.root, target_is_directory=True)
        result = audit(self.root)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(len(result['verified_claims']), 1)

    def test_source_has_no_real_secrets(self):
        source = Path(__file__).parents[1] / 'src'
        patterns = [r'AKIA[0-9A-Z]{16}', r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----', r'\b\d{3}-\d{2}-\d{4}\b', r'sk-[A-Za-z0-9]{20,}']
        for path in source.rglob('*.py'):
            text = path.read_text()
            for pattern in patterns:
                self.assertIsNone(re.search(pattern, text))


if __name__ == '__main__':
    unittest.main()
