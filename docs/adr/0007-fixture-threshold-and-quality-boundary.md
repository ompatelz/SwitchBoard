# ADR 0007: Fixture threshold and quality boundary

## Decision

Keep semantic reuse off by default and restricted to the synthetic fixed-answer model. Set its
configured threshold to `0.94`, selected from the calibration fixture only by zero observed false
positives, maximum positive acceptance, then highest threshold. Freeze that setting for the
disjoint held-out fixture run. Retain the reviewed subject gate and all tenant, version, expiry,
and response-reference checks. Broad natural-language requests remain ineligible.

## Evidence and limits

The pinned BGE-small ONNX model accepted one paraphrase and rejected one changed-subject negative
in each partition. The negatives are rejected by subject compatibility regardless of score, so
this dataset does not establish threshold safety against same-subject hard negatives. All 20 broad
hard-negative audit pairs bypass before embedding. Local mock-path measurement found semantic hits
slower than mock provider calls. There is no measured real-provider quality, traffic coverage, or
cost benefit. Expand reviewed eligible categories only with new labels and separate held-out
evidence; never infer answer equivalence from cosine score alone.
