"""Verify the clean extracted payload's content binding, not publication authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


PAYLOAD_FILES = frozenset({
    "reviewer_guard.py", "test_reviewer_guard.py", "demo.py", "README.md",
    "pyproject.toml", "verify_provenance.py", "provenance.json", "LICENSE",
})


def verify_payload(root: Path) -> str:
    root = root.resolve()
    git_metadata = root / ".git"
    if git_metadata.is_symlink() or (git_metadata.exists() and not git_metadata.is_dir()):
        raise ValueError("Git metadata must be a local directory")
    actual = {p.name for p in root.iterdir() if p.name != ".git"}
    if actual != PAYLOAD_FILES or any((root / name).is_symlink() or not (root / name).is_file() for name in actual):
        raise ValueError("payload must contain exactly the declared regular files")
    record = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    artifact = record["artifact"]
    digests = artifact["content_digests"]
    expected = PAYLOAD_FILES - {"provenance.json"}
    if set(artifact["path_scope"]) != expected or len(artifact["path_scope"]) != len(expected) or set(digests) != expected:
        raise ValueError("provenance scope must match the flattened payload")
    for name, expected_digest in digests.items():
        actual_digest = "sha256:" + hashlib.sha256((root / name).read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            raise ValueError("payload digest mismatch: " + name)
    digest = "sha256:" + hashlib.sha256(json.dumps(digests, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if digest != artifact["target_ref"]:
        raise ValueError("aggregate target digest mismatch")
    return digest


if __name__ == "__main__":
    print(verify_payload(Path(__file__).parent))
