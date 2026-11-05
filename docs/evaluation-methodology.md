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

## Planned measurements

After the embedding worker and retrieval path exist, sweep thresholds using only calibration data.
Choose a threshold from a declared false-positive risk budget, then freeze it before measuring on
held-out data. Report the selected model/version, normalization, vector dimension, cosine formula,
candidate count, compatibility rules, and every denominator. A false positive is an accepted
negative pair; a false negative is a rejected positive pair. Precision is accepted positives divided
by all accepted pairs. Coverage is accepted pairs divided by all eligible target pairs. Also report
false-positive rate among negative pairs and incorrect reuse among all evaluated pairs. Break
results out by risk category. For a zero denominator, report undefined rather than zero.

This tiny, intentionally hard dataset is a contract and regression seed, not a representative
traffic sample. Its positive class is especially small, so any future precision or coverage estimate
will have wide uncertainty. Synthetic labels need human review before a production quality claim.
No model, threshold, score, false-positive measurement, benchmark, or quality improvement is claimed
for this slice. Similarity measures vector direction; answer equivalence also depends on entities,
numbers, negation, units, time, instructions, and context.
