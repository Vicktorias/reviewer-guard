# GovernGrid Reviewer Guard

A small Python library and local CLI that evaluates whether a reviewer is
independent of the authors, material contributors, active writers and delegation
ancestors supplied for one exact software target. Apache-2.0, Python 3.11+,
standard library at runtime. No hosted service or paid account is needed.

## Quickstart

Download or clone this repository, then open its directory:

```bash
python -B verify_provenance.py
python -B -m reviewer_guard --demo
python -B -m unittest -v test_reviewer_guard.py
```

The demo uses only synthetic identities. It runs 16 labeled cases; success is
exit 0 and `mismatched_observations: 0`. It does not contact GitHub or record an
approval. Run the verifier before build/test commands create extra files.

To install the CLI into an isolated environment:

```bash
python -m venv .venv
# Linux/macOS:
.venv/bin/python -m pip install .
.venv/bin/reviewer-guard --demo
# Windows PowerShell:
.venv\Scripts\python -m pip install .
.venv\Scripts\reviewer-guard --demo
```

Installation may download the build tools declared in pyproject.toml. If
setuptools>=68 and wheel are already installed, an offline build is available:

```bash
python -m pip wheel --no-deps --no-build-isolation --no-index . --wheel-dir /tmp/reviewer-guard-wheel
```

No PyPI installation or package upload is required to use the source release.

## Use with a real context

Save this as `context.json`, replacing the synthetic values with verified IDs,
complete histories and the immutable digest of the actual target:

```json
{
  "reviewer_id": "reviewer-b",
  "project_id": "demo-project",
  "target_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "scope_id": "module-a",
  "author_ids": ["author-a"],
  "material_contributor_ids": [],
  "delegated_from_ids": [],
  "active_write_owner_ids": [],
  "provenance_complete": true
}
```

```bash
python -B -m reviewer_guard --context context.json
# Or, with the installed command:
reviewer-guard --context context.json
```

`--context -` reads standard input. The CLI accepts at most 65536 UTF-8 bytes,
rejects unknown keys, and converts JSON history arrays to tuples. It outputs only
the decision and fixed reason codes, not the supplied identities or raw input.

| Outcome | CLI exit | Meaning |
| --- | --- | --- |
| ELIGIBLE | 0 | No conflict found in the supplied complete context |
| INELIGIBLE | 1 | Author/contributor/write-owner/delegation conflict found |
| UNKNOWN | 2 | Context or provenance missing/malformed; no eligibility granted |

Invalid JSON, unreadable/oversized input and CLI usage errors also exit 2.
Consumers must not treat UNKNOWN or a command failure as approval.

## Python API

```python
from reviewer_guard import ReviewContext, evaluate_reviewer

context = ReviewContext(
    reviewer_id="reviewer-b", project_id="demo-project",
    target_digest="sha256:" + "b" * 64, scope_id="module-a",
    author_ids=("author-a",), material_contributor_ids=(),
    delegated_from_ids=(), active_write_owner_ids=(),
    provenance_complete=True,
)
print(evaluate_reviewer(context).outcome.value)  # ELIGIBLE
```

The API requires the exact ReviewContext type, built-in strings and built-in
tuple histories. Dynamic subclasses and incomplete records fail closed to UNKNOWN.
Missing histories are different from explicitly verified empty `()` histories.
`delegated_from_ids` must include every resolved ancestor; duplicate ancestors
return UNKNOWN. Any ancestor intersecting the author, contributor or active
WRITE-owner histories makes the reviewer INELIGIBLE.

Digests accept complete raw 40/64 hexadecimal values, `sha1:` plus 40 hex digits,
or `sha256:` plus 64 hex digits. Syntax is checked without trimming. IDs must be
nonempty/unpadded and exclude Unicode control, format and surrogate characters.
Legitimate Unicode is supported. No identity normalization is performed.

## Trust boundary and limitations

The caller must authenticate identities, resolve aliases and ancestry, classify
overlapping write scopes, bind the real artifact to the digest, and truthfully
attest that the supplied histories are complete. Visually similar Unicode IDs
and aliases can refer to the same actor; byte-distinct inputs are not resolved
here. Do not feed display names as authoritative IDs. Bound request sizes when
using the Python API in another service; only the CLI supplies an input-size cap.

This module does not authenticate a reviewer, discover concealed history, inspect
code, run a security review, check CI, enforce GitHub rules, authorize release,
merge, deploy or prove legal/IP ownership. ELIGIBLE is not GitHub APPROVED, a
security verdict or permission to publish. Apply your organization's separate
review and release rules. Fresh target/scope changes need fresh provenance.

## Synthetic demo and benchmark

```bash
python -B demo.py
python -B -m reviewer_guard --benchmark --iterations 100
```

The benchmark reports labeled outcomes, mismatch count and measured min/median/
p95/max latency per case, the module SHA-256 and Python version. Iterations are
bounded to 1–10000. Timings include evaluator and timer overhead, with no warmup;
p95 uses nearest rank. These synthetic measurements are not customer validation,
production throughput or a guarantee against every identity/integration attack.

## Content provenance and license

The eight-file source payload contains this library, tests, synthetic demo,
README, package metadata, verifier, provenance record and Apache-2.0 license.
`verify_provenance.py` checks exactly that layout and the seven non-circular
content hashes. A local `.git` directory is allowed for a clone; a `.git` file
or symlink is rejected. This does not inspect or certify repository history.
The provenance record itself needs an external release hash.
Content hashes verify bytes, not truth of authorship or review declarations.
Source builds, virtual environments and caches add files: verify a fresh payload.

## Version and feedback

v0.1.0 provides the bounded library, JSON CLI, synthetic demo/benchmark and content
verification. Dynamic Python subclasses fail closed. This initial source release
has no earlier public compatibility commitment or automatic update mechanism.
To roll back locally, reinstall a previously verified wheel or source checkout;
external automation must keep its own deployment/rollback controls.

Report issues with Python/package version, synthetic reproduction, expected and
observed outcome, exit code and source commit. Remove real actor IDs, private
repository data and secrets. Do not post live credentials in a public issue.
