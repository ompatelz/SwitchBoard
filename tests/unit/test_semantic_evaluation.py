"""Dataset loading rejects malformed labels, leakage, and duplicate records."""

import json
from pathlib import Path

import pytest

from switchboard.semantic_evaluation import load_prompt_pairs

DATASET = Path(__file__).resolve().parents[2] / "evaluation" / "semantic_pairs_v1.jsonl"


def test_dataset_is_deterministic_and_has_hard_negatives_in_each_split() -> None:
    pairs = load_prompt_pairs(DATASET)
    assert pairs == load_prompt_pairs(DATASET)
    assert len(pairs) == 20
    assert list(pairs) == sorted(pairs, key=lambda pair: pair.id)
    assert {pair.partition for pair in pairs} == {"calibration", "held_out"}
    assert {pair.group_id for pair in pairs if pair.partition == "calibration"}.isdisjoint(
        {pair.group_id for pair in pairs if pair.partition == "held_out"}
    )
    for partition in ("calibration", "held_out"):
        subset = [pair for pair in pairs if pair.partition == partition]
        assert len(subset) == 10
        assert sum(pair.reusable for pair in subset) == 1
        assert {pair.category for pair in subset if not pair.reusable} == {
            "entity",
            "number",
            "freshness",
            "negation",
            "unit",
            "format",
            "system_instruction",
            "conversation_context",
            "vocabulary_overlap",
        }


@pytest.mark.parametrize(
    "mutation",
    ["duplicate", "unknown_field", "bad_label", "cross_partition", "cross_request", "blank"],
)
def test_invalid_dataset_is_rejected(tmp_path: Path, mutation: str) -> None:
    lines = DATASET.read_text(encoding="utf-8").splitlines()
    if mutation == "duplicate":
        lines.append(lines[0])
    elif mutation == "blank":
        lines.insert(1, "")
    else:
        row = json.loads(lines[0])
        if mutation == "unknown_field":
            row["secret_extra"] = "not in schema"
        elif mutation == "bad_label":
            row["reusable"] = False
        else:
            row["id"] = "extra_cross_partition"
            row["partition"] = "held_out"
            if mutation == "cross_request":
                row["group_id"] = "new_group"
        lines.append(json.dumps(row))
    path = tmp_path / "pairs.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(ValueError):
        load_prompt_pairs(path)
