# Semantic reuse evaluation methodology

## Dataset and label

[`../evaluation/semantic_pairs_v1.jsonl`](../evaluation/semantic_pairs_v1.jsonl) contains 20
hand-authored synthetic pairs, version 1. Each record has strict source and target Chat Completion
requests, a risk category, a partition, a group ID, and a rationale. `reusable=true` means that a
complete cached answer to the source request could correctly satisfy the target request under the
same trusted tenant, model, provider policy, and versions. It does not mean the prompts merely discuss
the same topic. All text is synthetic; no user prompts, credentials, or private content were copied.

Ten pairs are for calibration and ten are held out. Each partition contains one clear paraphrase
and nine hard negatives: entity, number, freshness, negation, unit, output format, system
instruction, conversation context, and vocabulary overlap. Groups are disjoint across partitions;
the loader rejects a group that crosses the split, duplicate IDs, malformed records, blank lines,
identical requests, and inconsistent category/label combinations. It returns records sorted by ID.
The held-out examples must not guide model choice, prompt rules, or threshold selection.

## Fixture threshold selection and held-out check

The separate [fixture dataset](../evaluation/semantic_fixture_pairs_v1.jsonl) contains four
synthetic pairs under the only live eligible model: one positive and one changed-subject negative
in each partition. Calibration uses `stack` and `linked list`; held-out uses `heap` and `hash table`.
Subjects do not cross partitions. These are fixed canned answers, not sampled provider responses.

`uv run python scripts/calibrate_semantic_cache.py --model-dir <pinned-model-directory>` verifies
the pinned manifest, embeds the fixture prompts, and sweeps cosine thresholds from 0.80 to 1.00
in 0.01 steps. Selection uses **calibration only**: minimize observed false positives, maximize
accepted positives, then choose the highest threshold. The selected `0.94` is frozen before the
held-out calculation. The [machine-readable run](semantic-calibration-results.json) records the
model revision, 384 dimensions, normalization, candidate count 3, every score, host, run count,
evaluated commit, denominators, and category counts. A false positive is an accepted negative; a
false negative is a rejected positive. Precision is accepted positives divided by all accepted;
false-positive rate is accepted negatives divided by all negatives; coverage is accepted pairs
divided by eligible pairs; incorrect-reuse rate is accepted negatives divided by all pairs. A
zero denominator is reported as `null`.

| Partition | Pairs | Positives | Negatives | Accepted | False positives | Precision | Coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Calibration | 2 | 1 | 1 | 1 | 0 | 1/1 | 1/2 |
| Held-out | 2 | 1 | 1 | 1 | 0 | 1/1 | 1/2 |

Both changed-subject negatives are blocked by the subject gate even before score acceptance; the
threshold has **no eligible same-subject negative** to distinguish. Both paraphrases were accepted
and neither split had a false negative. The original 20-pair hard-negative dataset is audited by
category: all 20 requests bypass before embedding under the live default-deny rule, including its
two positives. Thus it measures policy coverage, not score quality. Precision 1/1 and false-positive
rate 0/1 on the held-out fixture are observations with almost no statistical power. No
real-provider quality, traffic coverage, or cost improvement is established. This is a negative
result for broad semantic reuse; it stays disabled by default. Similarity measures vector
direction, while answer equivalence also depends on entities, numbers, negation, units, time,
instructions, and context. See [ADR 0007](adr/0007-fixture-threshold-and-quality-boundary.md).
