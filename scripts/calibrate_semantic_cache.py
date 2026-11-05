"""Run a pinned-model fixture sweep and write separate held-out evidence."""

import argparse
import json
import os
import platform
import subprocess
from pathlib import Path

from switchboard.embedding_model import MODEL_DIMENSION, MODEL_NAME, MODEL_REVISION
from switchboard.embedding_service import FastEmbedEncoder
from switchboard.semantic_calibration import (
    THRESHOLDS,
    fixture_pair_gate,
    metrics,
    score_pairs,
    select_threshold,
)
from switchboard.semantic_evaluation import load_prompt_pairs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument(
        "--fixture-data", type=Path, default=Path("evaluation/semantic_fixture_pairs_v1.jsonl")
    )
    parser.add_argument(
        "--hard-negatives", type=Path, default=Path("evaluation/semantic_pairs_v1.jsonl")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("docs/semantic-calibration-results.json")
    )
    arguments = parser.parse_args()
    fixture = load_prompt_pairs(arguments.fixture_data)
    hard_negatives = load_prompt_pairs(arguments.hard_negatives)
    encoder = FastEmbedEncoder(arguments.model_dir)
    rows = score_pairs(fixture, encoder)
    calibration = tuple(row for row in rows if row.pair.partition == "calibration")
    held_out = tuple(row for row in rows if row.pair.partition == "held_out")
    threshold = select_threshold(calibration)
    blocked = {
        category: sum(
            1
            for pair in hard_negatives
            if pair.category == category and not all(fixture_pair_gate(pair))
        )
        for category in sorted({pair.category for pair in hard_negatives})
    }
    report = {
        "dataset": str(arguments.fixture_data).replace("\\", "/"),
        "hard_negative_dataset": str(arguments.hard_negatives).replace("\\", "/"),
        "label": (
            "The complete fixed source answer can correctly answer the target under identical scope"
        ),
        "model": MODEL_NAME,
        "revision": MODEL_REVISION,
        "dimension": MODEL_DIMENSION,
        "normalized": True,
        "similarity": "cosine (dot product of unit vectors)",
        "candidate_count": 3,
        "risk_priority": (
            "zero observed calibration false positives, then maximum true positives, "
            "then highest threshold"
        ),
        "threshold_grid": list(THRESHOLDS),
        "selected_threshold": threshold,
        "calibration": metrics(calibration, threshold),
        "held_out": metrics(held_out, threshold),
        "pairs": [
            {
                "id": row.pair.id,
                "partition": row.pair.partition,
                "category": row.pair.category,
                "reusable": row.pair.reusable,
                "similarity": round(row.similarity, 9),
                "eligible": row.eligible,
                "same_subject": row.same_subject,
                "accepted": row.accepted(threshold),
            }
            for row in rows
        ],
        "hard_negative_audit": {
            "pairs": len(hard_negatives),
            "blocked_before_embedding": sum(blocked.values()),
            "by_category": blocked,
        },
        "runs": 1,
        "host": {
            "system": platform.system(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
        "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "limitations": [
            "Four fixture pairs, one positive and one negative per partition; "
            "no statistical quality estimate",
            "Negative fixture pairs change subject and are rejected by a hard gate "
            "regardless of score",
            "The twenty broad hard-negative pairs are outside the live eligibility boundary",
            "Synthetic fixed answers and local CPU inference do not measure "
            "real-provider quality or cost",
        ],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "threshold": threshold,
                "calibration": report["calibration"],
                "held_out": report["held_out"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
