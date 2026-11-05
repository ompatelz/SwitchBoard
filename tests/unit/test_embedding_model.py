"""Local manifest rejects missing, modified, or mislabeled model assets."""

import json
from pathlib import Path

import pytest

from switchboard.embedding_model import MANIFEST_NAME, MODEL_FILES, verify_manifest, write_manifest


def test_manifest_checks_identity_and_file_bytes(tmp_path: Path) -> None:
    for name in MODEL_FILES:
        (tmp_path / name).write_bytes(name.encode())
    write_manifest(tmp_path)
    verify_manifest(tmp_path)
    (tmp_path / MODEL_FILES[0]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="file mismatch"):
        verify_manifest(tmp_path)


def test_manifest_rejects_wrong_revision_and_missing_file(tmp_path: Path) -> None:
    for name in MODEL_FILES:
        (tmp_path / name).write_bytes(name.encode())
    write_manifest(tmp_path)
    manifest_path = tmp_path / MANIFEST_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["revision"] = "other"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_manifest(tmp_path)
    manifest_path.unlink()
    with pytest.raises(ValueError, match="manifest is invalid"):
        verify_manifest(tmp_path)
