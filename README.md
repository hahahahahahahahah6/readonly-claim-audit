# readonly-claim-audit

Version 0.1.0. An offline, stdlib-only static auditor for documented read-only
claims in Python projects. Python 3.9 or later is required. It reads source and
Markdown; it never imports or executes the audited project and makes no network
requests. The audit itself does not modify project files.

## Installation and use

```sh
python3 -m pip install .
readonly-claim-audit .
readonly-claim-audit . --json
readonly-claim-audit . --fail-on HIGH --verbose
readonly-claim-audit . --ignore documented-readonly-write
readonly-claim-audit --version
```

The path defaults to the current directory. Exit 0 means PASS, 2 means FAIL,
and 1 means a usage or input error (including invalid Python or unreadable input).
The default failure threshold is MEDIUM. `--fail-on HIGH` still prints MEDIUM
findings but returns 0 for those alone. `--ignore RULE,...` removes matching
findings before deciding status. `--verbose` includes verified claims in human
output. `--version` prints `0.1.0`.

JSON contains `status`, `findings`, and `verified_claims`. Each finding has
`rule`, `severity`, `file`, `line`, and `message`. Paths are relative to the
project root; lines are one-based. Human finding lines use
`SEVERITY rule file:line message`, followed by the overall status.

## Claims and rules

Claims come only from root `README.md` and `docs/**/*.md`, excluding backtick
and tilde fenced blocks. Case-insensitive patterns are: read-only/read only;
does not modify/doesn't modify/never modifies/never modify; does not write/
doesn't write/never writes/never write/no writes; does not change/never changes.
The change phrases are interpreted in the filesystem context; semantic context
is not inferred. A claim is a unique (file, line, kind) triple. Repeated phrases
of one kind on one line produce one claim. Positive statements such as
“writes a report” are not claims.

* `documented-readonly-write` (HIGH): claims and production write evidence.
* `documented-readonly-write-test-only` (MEDIUM): claims and writes exclusively
  in test files. A test file is under `tests/` or `fixtures/`, or named
  `test_*.py` or `*_test.py`, at any depth.
* If production writes exist, report those; the test-only rule does not apply.
* One finding per (rule, evidence-file, evidence-line), regardless of claim
  count. Three writes on different lines yield three findings. Multiple write
  calls on one line yield one finding naming a representative call.
* No Python source means HIGH findings at each claim location, one per claim.
* No claims means PASS, even with writes. There are no reverse rules.

Verified claims are claims with Python source present and no write evidence.
Ignoring a finding does not turn its claims into verified claims.

## Static write-evidence table

| Calls | Evidence |
| --- | --- |
| `open`, `io.open` | Literal positional or `mode=` string containing `w`, `a`, `x`, or `+` |
| Any receiver's `write_text`, `write_bytes` | Always |
| `os.remove`, `os.unlink`, `os.rename`, `os.replace` | Always |
| `os.mkdir`, `os.makedirs`, `os.rmdir`, `os.removedirs` | Always |
| `shutil.copy`, `shutil.copy2`, `shutil.move`, `shutil.rmtree` | Always |
| `os.chmod`, `os.utime` | Excluded: metadata-only |
| `print(..., file=...)` | Excluded: the opening call provides evidence |

Read modes `r` and `rb` and omitted modes are not evidence. Variable or computed
modes are UNKNOWN and skipped, even if a nearby assignment is a literal.
Symlinked source/docs files and symlink directories are skipped. `.env` contents
are never read. No target files are opened for writing.

## Differentiation

Bandit and Ruff detect code issues, rather than documentation promises.
privacy-claim-audit covers network/telemetry evidence. The format, schema, API,
and config claim auditors cover formats, fields, symbols, and defaults rather
than filesystem writes. `find . -writable` and permission checks measure actual
writability, without comparing documentation claims. No tool specifically
comparing documented read-only promises with static source writes is known to
this project's authors; this is not an exhaustive market claim.

## Limitations

PASS is not a proof of runtime safety. This tool does no call-graph, reachability,
alias, data-flow, or semantic prose analysis. Dead code counts. Imported aliases,
wrappers, dynamically selected methods, subprocesses, native extensions, other
languages, and unlisted write APIs can evade detection. Any receiver with a
`write_text` or `write_bytes` attribute counts, without requiring a pathlib
import; unrelated methods can therefore produce false positives. Names such as
`os` can be shadowed and still count. Claims are project-wide, so qualified or
negated prose may be overinterpreted. Inline code is not excluded. Only fenced
blocks are excluded; complex Markdown constructs are not fully parsed.

All regular `.py` files under the target are scanned, including vendored code
and virtual environments; choose a clean project tree. UTF-8 text and parseable
Python are required. Static checks do not establish actual filesystem permissions.
The auditor reads input without a snapshot, so concurrent filesystem changes
can affect results. Metadata writes and print destinations are excluded as
specified above. Findings should be reviewed by a person.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m build
```

MIT licensed. No runtime dependencies.
