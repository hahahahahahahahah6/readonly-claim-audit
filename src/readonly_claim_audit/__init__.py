"""Static documentation versus filesystem-write audit; no target code is executed."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys

__version__ = "0.1.0"
HIGH_RULE = "documented-readonly-write"
TEST_RULE = "documented-readonly-write-test-only"
PATTERNS = {
    "read-only": r"\bread[- ]only\b",
    "no-modify": r"\b(?:does not modify|doesn't modify|never modifies|never modify)\b",
    "no-write": r"\b(?:does not write|doesn't write|never writes|never write|no writes)\b",
    "no-change": r"\b(?:does not change|never changes)\b",
}
OS_WRITES = {"remove", "unlink", "rename", "replace", "mkdir", "makedirs", "rmdir", "removedirs"}
SHUTIL_WRITES = {"copy", "copy2", "move", "rmtree"}


def files(root):
    """Walk without following symlink files or directories, including hidden ones."""
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            path = Path(directory) / name
            if not path.is_symlink():
                yield path


def claims_in(text, name):
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[marker.end():].strip():
                fence = None
            continue
        if fence is None:
            for kind, pattern in PATTERNS.items():
                if re.search(pattern, line, re.I):
                    yield {"file": name, "line": number, "kind": kind}


def write_call(node):
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    name = func.id if isinstance(func, ast.Name) else None
    if isinstance(func, ast.Attribute):
        if func.attr in {"write_text", "write_bytes"}:
            return func.attr
        if isinstance(func.value, ast.Name):
            module = func.value.id
            name = module + "." + func.attr
            if (module == "os" and func.attr in OS_WRITES) or (module == "shutil" and func.attr in SHUTIL_WRITES):
                return name
    if name in {"open", "io.open"}:
        mode = node.args[1] if len(node.args) > 1 else None
        for keyword in node.keywords:
            if keyword.arg == "mode":
                mode = keyword.value
        if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and any(c in mode.value for c in "wax+"):
            return name
    return None


def audit(root, ignored=(), fail_on="MEDIUM"):
    root = Path(root)
    if not root.is_dir():
        raise ValueError("path must be an existing directory")
    claims, evidence, sources = [], [], 0
    for path in files(root):
        relative = path.relative_to(root)
        name = relative.as_posix()
        if name == "README.md" or (relative.parts[0] == "docs" and path.suffix == ".md"):
            claims.extend(claims_in(path.read_text(encoding="utf-8"), name))
        if path.suffix != ".py":
            continue
        sources += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=name)
        test_only = bool({"tests", "fixtures"}.intersection(relative.parts[:-1])) or path.name.startswith("test_") or path.name.endswith("_test.py")
        for node in ast.walk(tree):
            call = write_call(node)
            if call:
                evidence.append((name, node.lineno, call, test_only))
    findings = []
    if claims:
        production = any(not item[3] for item in evidence)
        seen = set()
        for name, line, call, test_only in sorted(evidence):
            if production and test_only:
                continue
            rule = HIGH_RULE if production else TEST_RULE
            key = (rule, name, line)
            if key not in seen:
                seen.add(key)
                findings.append(dict(rule=rule, severity="HIGH" if production else "MEDIUM", file=name, line=line, message="Read-only claim contradicted by " + call + "()"))
        if not sources:
            for claim in claims:
                findings.append(dict(rule=HIGH_RULE, severity="HIGH", file=claim["file"], line=claim["line"], message="Read-only claim cannot be checked: no Python source files"))
    verified = claims if sources and not evidence else []
    findings = [f for f in findings if f["rule"] not in ignored]
    failed = any(f["severity"] == "HIGH" or fail_on == "MEDIUM" for f in findings)
    return dict(status="FAIL" if failed else "PASS", findings=findings, verified_claims=verified)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, "error: " + message + "\n")


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail-on", choices=["HIGH", "MEDIUM"], default="MEDIUM")
    parser.add_argument("--ignore", default="", metavar="RULE,...")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        result = audit(args.path, args.ignore.split(","), args.fail_on)
    except (OSError, ValueError, SyntaxError) as error:
        # Never echo source text, which could contain private information.
        print("error: cannot audit input (" + type(error).__name__ + ")", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result))
    else:
        for finding in result["findings"]:
            print("{severity} {rule} {file}:{line} {message}".format(**finding))
        if args.verbose:
            for claim in result["verified_claims"]:
                print("VERIFIED {file}:{line} {kind}".format(**claim))
        print(result["status"])
    return 2 if result["status"] == "FAIL" else 0
