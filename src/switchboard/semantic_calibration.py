"""Reproducible fixture threshold sweep with a frozen held-out decision."""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from switchboard.auth import TenantIdentity
from switchboard.embedding_model import MODEL_REVISION
from switchboard.embedding_service import Encoder
from switchboard.semantic_evaluation import PromptPair
from switchboard.semantic_policy import (
    STATIC_FIXTURE_MODEL,
    SemanticEligibilityContext,
    evaluate_lookup,
    static_definition_subject,
)

THRESHOLDS = tuple(index / 100 for index in range(80, 101))


@dataclass(frozen=True)
class ScoredPair:
    pair: PromptPair
    similarity: float
    eligible: bool
    same_subject: bool

    def accepted(self, threshold: float) -> bool:
        return self.eligible and self.same_subject and self.similarity >= threshold


def _fixture_context(request: PromptPair, *, source: bool) -> SemanticEligibilityContext:
    body = request.source if source else request.target
    return SemanticEligibilityContext(
        tenant=TenantIdentity("synthetic-evaluation"),
        provider_policy="fixture-only",
        embedding_model_version=MODEL_REVISION,
        supported_model=STATIC_FIXTURE_MODEL,
        trusted_static_definition=static_definition_subject(body) is not None,
        provider_compatible=True,
        sensitive_input=False,
    )


def validate_fixture_split(pairs: Sequence[PromptPair]) -> None:
    """Keep held-out subjects distinct and require both labels in each split."""
    subjects: dict[str, set[str]] = {"calibration": set(), "held_out": set()}
    labels: dict[str, set[bool]] = {"calibration": set(), "held_out": set()}
    for pair in pairs:
        if pair.source.model != STATIC_FIXTURE_MODEL or pair.target.model != STATIC_FIXTURE_MODEL:
            raise ValueError("fixture pair uses an unsupported model")
        source = static_definition_subject(pair.source)
        target = static_definition_subject(pair.target)
        if source is None or target is None:
            raise ValueError("fixture pair is outside the live eligibility boundary")
        if pair.reusable != (source == target):
            raise ValueError("fixture label disagrees with the fixed-answer subject")
        subjects[pair.partition].update((source, target))
        labels[pair.partition].add(pair.reusable)
    if subjects["calibration"] & subjects["held_out"]:
        raise ValueError("fixture subject crosses calibration and held-out splits")
    if any(values != {True, False} for values in labels.values()):
        raise ValueError("each fixture split needs positive and negative labels")


def fixture_pair_gate(pair: PromptPair) -> tuple[bool, bool]:
    eligible = evaluate_lookup(pair.source, _fixture_context(pair, source=True)).eligible and (
        evaluate_lookup(pair.target, _fixture_context(pair, source=False)).eligible
    )
    same_subject = static_definition_subject(pair.source) == static_definition_subject(pair.target)
    return eligible, same_subject


def score_pairs(pairs: Sequence[PromptPair], encoder: Encoder) -> tuple[ScoredPair, ...]:
    validate_fixture_split(pairs)
    prompts = sorted(
        {body.messages[0].content for pair in pairs for body in (pair.source, pair.target)}
    )
    vectors: dict[str, list[float]] = {}
    for offset in range(0, len(prompts), 16):
        batch = prompts[offset : offset + 16]
        result = encoder.encode(batch)
        if len(result) != len(batch):
            raise ValueError("embedding count mismatch")
        vectors.update(zip(batch, result, strict=True))
    scored = []
    for pair in pairs:
        source = pair.source.messages[0].content
        target = pair.target.messages[0].content
        left, right = vectors[source], vectors[target]
        if len(left) != 384 or len(right) != 384:
            raise ValueError("embedding dimension mismatch")
        for vector in (left, right):
            norm = math.sqrt(math.fsum(component * component for component in vector))
            if not math.isfinite(norm) or not math.isclose(norm, 1.0, abs_tol=1e-4):
                raise ValueError("embedding is not a finite unit vector")
        similarity = math.fsum(a * b for a, b in zip(left, right, strict=True))
        if not math.isfinite(similarity):
            raise ValueError("nonfinite similarity")
        eligible, same_subject = fixture_pair_gate(pair)
        scored.append(
            ScoredPair(
                pair=pair,
                similarity=similarity,
                eligible=eligible,
                same_subject=same_subject,
            )
        )
    return tuple(scored)


def metrics(rows: Sequence[ScoredPair], threshold: float) -> dict[str, object]:
    accepted = [row for row in rows if row.accepted(threshold)]
    positives = [row for row in rows if row.pair.reusable]
    negatives = [row for row in rows if not row.pair.reusable]
    true_positive = sum(row.pair.reusable for row in accepted)
    false_positive = len(accepted) - true_positive
    eligible = sum(row.eligible for row in rows)
    by_category = Counter(row.pair.category for row in rows)
    accepted_by_category = Counter(row.pair.category for row in accepted)
    return {
        "pairs": len(rows),
        "eligible_pairs": eligible,
        "positive_pairs": len(positives),
        "negative_pairs": len(negatives),
        "accepted": len(accepted),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": len(positives) - true_positive,
        "precision": true_positive / len(accepted) if accepted else None,
        "false_positive_rate": false_positive / len(negatives) if negatives else None,
        "coverage": len(accepted) / eligible if eligible else None,
        "positive_coverage": true_positive / len(positives) if positives else None,
        "incorrect_reuse_rate": false_positive / len(rows) if rows else None,
        "by_category": {
            category: {"pairs": count, "accepted": accepted_by_category[category]}
            for category, count in sorted(by_category.items())
        },
    }


def select_threshold(calibration: Sequence[ScoredPair]) -> float:
    if not calibration or any(row.pair.partition != "calibration" for row in calibration):
        raise ValueError("threshold selection requires calibration rows only")
    candidates = []
    for threshold in THRESHOLDS:
        false_positive = sum(
            row.accepted(threshold) and not row.pair.reusable for row in calibration
        )
        true_positive = sum(row.accepted(threshold) and row.pair.reusable for row in calibration)
        candidates.append((false_positive, -true_positive, -threshold, threshold))
    return min(candidates)[3]
