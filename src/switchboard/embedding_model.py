"""Reviewed local model identity and file-integrity contract."""

import hashlib
import json
from pathlib import Path

MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_REPO = "qdrant/bge-small-en-v1.5-onnx-q"
MODEL_REVISION = "aa8f8b060edb00e03bfdd08813a2949946c8ba55"
MODEL_DIMENSION = 384
MODEL_FILES = (
    "config.json",
    "model_optimized.onnx",
    "ort_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
)
MANIFEST_NAME = "switchboard-model-manifest.json"


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(directory: Path) -> None:
    payload = {
        "model": MODEL_NAME,
        "repository": MODEL_REPO,
        "revision": MODEL_REVISION,
        "dimension": MODEL_DIMENSION,
        "files": {name: file_digest(directory / name) for name in MODEL_FILES},
    }
    target = directory / MANIFEST_NAME
    temporary = directory / f"{MANIFEST_NAME}.tmp"
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.replace(target)


def verify_manifest(directory: Path) -> None:
    try:
        payload = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
        if (
            payload["model"] != MODEL_NAME
            or payload["repository"] != MODEL_REPO
            or payload["revision"] != MODEL_REVISION
            or payload["dimension"] != MODEL_DIMENSION
            or set(payload["files"]) != set(MODEL_FILES)
        ):
            raise ValueError("embedding model identity mismatch")
        for name in MODEL_FILES:
            if payload["files"][name] != file_digest(directory / name):
                raise ValueError("embedding model file mismatch")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("embedding model manifest is invalid") from exc
