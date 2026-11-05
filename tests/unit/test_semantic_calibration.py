"""Threshold selection uses calibration rows and records explicit denominators."""

from dataclasses import replace
from pathlib import Path

import pytest

from switchboard.semantic_calibration import (
    ScoredPair,
    metrics,
    select_threshold,
    validate_fixture_split,
)
from switchboard.semantic_evaluation import load_prompt_pairs

FIXTURE = Path(__file__).resolve().parents[2] / "evaluation" / "semantic_fixture_pairs_v1.jsonl"


def test_fixture_split_has_distinct_subjects_and_labels() -> None:
    pairs = load_prompt_pairs(FIXTURE)
    validate_fixture_split(pairs)
    assert len(pairs) == 4
    bad = list(pairs)
    held = next(index for index, pair in enumerate(bad) if pair.id == "fixture_eval_positive")
    calibration = next(pair for pair in bad if pair.id == "fixture_cal_positive")
    bad[held] = bad[held].model_copy(
        update={"source": calibration.source, "target": calibration.target}
    )
    with pytest.raises(ValueError, match="crosses"):
        validate_fixture_split(bad)


def test_threshold_is_frozen_before_held_out_scoring() -> None:
    pairs = load_prompt_pairs(FIXTURE)
    scores = {
        "fixture_cal_positive": 0.949,
        "fixture_cal_subject": 0.99,
        "fixture_eval_positive": 0.80,
        "fixture_eval_subject": 0.99,
    }
    rows = tuple(ScoredPair(pair, scores[pair.id], True, pair.reusable) for pair in pairs)
    calibration = tuple(row for row in rows if row.pair.partition == "calibration")
    held_out = tuple(row for row in rows if row.pair.partition == "held_out")
    threshold = select_threshold(calibration)
    assert threshold == 0.94
    assert metrics(calibration, threshold)["false_positive"] == 0
    assert metrics(held_out, threshold)["false_negative"] == 1
    with pytest.raises(ValueError, match="calibration rows only"):
        select_threshold(rows)
    changed_held_out = tuple(replace(row, similarity=1.0) for row in held_out)
    assert select_threshold(calibration) == threshold
    assert metrics(changed_held_out, threshold)["false_negative"] == 0


def test_zero_acceptance_has_undefined_precision() -> None:
    rows = tuple(ScoredPair(pair, 0.0, True, pair.reusable) for pair in load_prompt_pairs(FIXTURE))
    result = metrics(rows, 1.0)
    assert result["precision"] is None
    assert result["accepted"] == 0
    assert result["false_positive_rate"] == 0
