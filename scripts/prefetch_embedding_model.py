"""Fetch the exact reviewed ONNX export during image build or local setup."""

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download

from switchboard.embedding_model import MODEL_FILES, MODEL_REPO, MODEL_REVISION, write_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", type=Path)
    args = parser.parse_args()
    target: Path = args.model_dir.resolve()
    snapshot_download(
        repo_id=MODEL_REPO,
        revision=MODEL_REVISION,
        allow_patterns=list(MODEL_FILES),
        local_dir=target,
    )
    missing = [name for name in MODEL_FILES if not (target / name).is_file()]
    if missing:
        raise RuntimeError(f"model download incomplete: {', '.join(missing)}")
    write_manifest(target)
    print(f"Pinned model files ready in {target}")


if __name__ == "__main__":
    main()
