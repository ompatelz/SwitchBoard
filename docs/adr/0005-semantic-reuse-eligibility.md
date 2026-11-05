# ADR 0005: Default-deny semantic reuse eligibility

- **Status:** Accepted for the eligibility foundation
- **Date:** 2026-11-05

## Context

Exact matching already includes tenant and provider-policy inputs. Semantic matching can retrieve
nearby wording whose correct answer differs. Retrieval must therefore be treated as a candidate
source, never as proof of equivalent answers.

## Decision

Keep eligibility in a pure typed module. Require trusted server-side static-definition
classification, compatible provider policy, non-sensitive text, one user turn, non-streaming mode,
supported model, and narrow prompt syntax. Reject missing evidence by default. A separate storage
decision requires a complete compatible response. Return fixed reason codes and a server-derived,
versioned isolation scope only for eligible requests. Do not connect the module to the gateway until
the embedding, vector, and acceptance gates are implemented and tested together.

## Consequences

The first safe production outcome is no semantic reuse. The narrow syntax may reject useful prompts;
that is preferable to silent incorrect reuse before labeled evidence exists. Regex checks cannot
reliably classify arbitrary language, so the later server-side task classifier and acceptance rules
must be reviewed against hard negatives. The synthetic dataset provides calibration and held-out
partitions, but no threshold or quality claim. An LLM classifier and client-declared eligibility are
rejected because they add nondeterminism or let the caller control a safety gate.
