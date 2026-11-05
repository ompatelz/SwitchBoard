"""Strict, deterministic loading of synthetic semantic-reuse evaluation pairs."""

import json
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from switchboard.contracts import ChatCompletionRequest, StrictContract

Partition = Literal["calibration", "held_out"]
RiskCategory = Literal[
    "paraphrase",
    "entity",
    "number",
    "freshness",
    "negation",
    "unit",
    "format",
    "system_instruction",
    "conversation_context",
    "vocabulary_overlap",
]


class PromptPair(StrictContract):
    """Label means a cached answer to source can safely answer target."""

    id: str = Field(pattern=r"^[a-z0-9_]+$", min_length=1, max_length=64)
    group_id: str = Field(pattern=r"^[a-z0-9_]+$", min_length=1, max_length=64)
    partition: Partition
    category: RiskCategory
    source: ChatCompletionRequest
    target: ChatCompletionRequest
    reusable: bool
    rationale: str = Field(min_length=10, max_length=400)

    @model_validator(mode="after")
    def validate_label(self) -> Self:
        if self.source == self.target:
            raise ValueError("identical requests belong in the exact-cache evaluation")
        if self.reusable and self.category != "paraphrase":
            raise ValueError("positive labels must be clear paraphrases")
        if not self.reusable and self.category == "paraphrase":
            raise ValueError("paraphrase category requires a positive label")
        return self


def load_prompt_pairs(path: Path) -> tuple[PromptPair, ...]:
    """Validate every JSONL record and reject duplicate IDs or split leakage."""
    pairs: list[PromptPair] = []
    ids: set[str] = set()
    groups: dict[str, Partition] = {}
    requests: dict[str, Partition] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"blank dataset line {line_number}")
        try:
            pair = PromptPair.model_validate(json.loads(line))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid dataset line {line_number}") from exc
        if pair.id in ids:
            raise ValueError(f"duplicate pair ID on line {line_number}")
        if pair.group_id in groups and groups[pair.group_id] != pair.partition:
            raise ValueError(f"group crosses dataset partitions on line {line_number}")
        for request in (pair.source, pair.target):
            canonical = request.model_dump_json()
            if canonical in requests and requests[canonical] != pair.partition:
                raise ValueError(f"request crosses dataset partitions on line {line_number}")
            requests[canonical] = pair.partition
        ids.add(pair.id)
        groups[pair.group_id] = pair.partition
        pairs.append(pair)
    if {pair.partition for pair in pairs} != {"calibration", "held_out"}:
        raise ValueError("dataset needs calibration and held-out partitions")
    return tuple(sorted(pairs, key=lambda pair: pair.id))
