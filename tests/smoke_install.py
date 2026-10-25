"""Install the built wheel into a fresh temporary venv and check its CLI."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import venv


def check(command, expected):
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == expected, (command, result.returncode, result.stdout, result.stderr)
    return result.stdout


def run():
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='readonly-audit-smoke-') as temporary:
        base = Path(temporary)
        environment = base / 'venv'
        venv.EnvBuilder(with_pip=True).create(environment)
        interpreter = environment / 'bin/python3'
        wheel = project / 'dist/readonly_claim_audit-0.1.0-py3-none-any.whl'
        check([str(interpreter), '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)], 0)
        cli = str(environment / 'bin/readonly-claim-audit')
        assert check([cli, '--version'], 0) == '0.1.0\n'
        for name, code, expected, rule in [
            ('good', 'open("data", "r")\np.read_text()\njson.load(stream)', 0, None),
            ('bad', 'p.write_text("x")', 2, 'documented-readonly-write'),
            ('test-only', 'p.write_bytes(b"x")', 2, 'documented-readonly-write-test-only'),
        ]:
            fixture = base / name
            fixture.mkdir()
            (fixture / 'README.md').write_text('Read-only.\n')
            folder = fixture / ('tests' if name == 'test-only' else 'src')
            folder.mkdir()
            (folder / 'app.py').write_text(code)
            result = json.loads(check([cli, str(fixture), '--json'], expected))
            assert result['status'] == ('FAIL' if expected else 'PASS')
            if rule:
                assert len(result['findings']) == 1
                finding = result['findings'][0]
                assert finding['rule'] == rule
                assert finding['severity'] == ('MEDIUM' if name == 'test-only' else 'HIGH')
            else:
                assert len(result['verified_claims']) == 1
            if name == 'test-only':
                out = check([cli, str(fixture), '--fail-on', 'HIGH'], 0)
                assert 'MEDIUM documented-readonly-write-test-only' in out
        print('Fresh-venv smoke: good PASS/0, bad HIGH FAIL/2, test-only MEDIUM FAIL/2 and HIGH threshold PASS/0; version and JSON valid.')


if __name__ == '__main__':
    run()
