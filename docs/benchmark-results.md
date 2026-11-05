# Phase 2D local baseline measurements

Measured 2026-11-04 on a Windows 11 host with a 13th Gen Intel Core i7-13700H (14 cores, 20
logical processors) and 15.7 GiB RAM, using Docker Desktop engine 29.9.2. The host client used
Python 3.12.9, FastAPI 0.162.0, HTTPX 0.28.1, redis-py 8.1.0, and Uvicorn 0.54.0. The locked
gateway image used Python 3.12.16, Redis 7.4 ran in Compose, and each gateway was one Uvicorn
worker. The measured application code was commit `b654252445ec8210fb857360ed712df59709ece0`.
The later `stream_provider_events` type annotation and test/document edits did not alter request
execution. These are local mock measurements, not paid-provider or production throughput results.

## Workload and method

[`../scripts/benchmark_phase2.py`](../scripts/benchmark_phase2.py) made three runs of 30 buffered
requests per case over host loopback. Each call had one short synthetic user message, model
`mock-v1`, and the same development tenant. The mock provider had no configured response delay;
its response is deterministic CPU work, not model inference. Normal cases used 2,000 requests per
60-second tenant window to avoid benchmarking policy rejection. The cache TTL was 300 seconds.
The cache-hit case warmed one key per run before timing; miss and controlled-concurrency cases used
new prompts. The direct mock and uncached gateway cases also used new prompts. The uncached gateway
had a configured secondary mock endpoint pointing at the same mock provider, which makes Phase 2B
cache eligibility false. No provider failure or fallback occurred during the benchmark. The two
gateway processes had separate local circuits, pools, and metrics but shared the Redis instance.

Per-request time spans client POST through reading and validating the buffered response. p50, p95,
and p99 below are nearest-rank percentiles over all 90 samples in each case, in milliseconds.
Throughput is 90 divided by the sum of the three measured run wall times; setup, warmups, and
inter-case idle time are excluded. Sequential cases used concurrency 1; the controlled case used
concurrency 4. The raw per-run timings, status counts, and workload prefix are in
[`benchmark-data.json`](benchmark-data.json).

| Case | Requests | Concurrency | p50 ms | p95 ms | p99 ms | Requests/s | HTTP errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct mock provider | 90 | 1 | 1.56 | 2.70 | 6.49 | 559.01 | 0 |
| Gateway, exact cache bypass | 90 | 1 | 3.62 | 4.45 | 14.85 | 257.14 | 0 |
| Gateway, exact cache miss | 90 | 1 | 4.25 | 5.18 | 6.35 | 229.01 | 0 |
| Gateway, warmed exact hit | 90 | 1 | 3.02 | 5.33 | 6.77 | 302.01 | 0 |
| Gateway, new prompts | 90 | 4 | 10.14 | 13.06 | 20.51 | 371.90 | 0 |

The Prometheus cache-counter deltas matched the workload: cached gateway **90 hits, 183 misses,
183 writes, 0 cache errors** (the three warmups explain the additional misses); uncached gateway
**90 bypasses**. Cache hits avoided upstream calls, but their p95 overlapped misses in this short
run. The direct mock result gives context for the separate provider hop; subtracting medians would
not isolate exact gateway overhead because scheduling and network paths differ. Concurrency raised
aggregate throughput while increasing per-request latency, a normal queueing trade-off even below
the worker's 32-permit limit. No model-quality, cost, or real-provider speedup is inferred.

## Separate Redis failure experiment

With the normal gateway healthy, Compose stopped Redis. The same script's `--redis-outage` mode
then sent three sequential runs of 30 synthetic requests. All **90/90** returned HTTP 503 with
`rate_limit_unavailable`; no completion was falsely reported. p50 was **254.325 ms**, p95
**258.158 ms**, p99 **285.245 ms**, and measured throughput **3.92 requests/s**. The error rate
was **100% by design** because enforcement fails closed. The 0.25-second configured Redis socket
timeout dominates this local outage result. Raw timings are in
[`benchmark-redis-outage.json`](benchmark-redis-outage.json). This is a controlled stopped-Redis
case, not a general network-partition distribution.

## Reproduction

Generate a random development key and digest using the commands in the README. In the same shell:

```powershell
$env:SWITCHBOARD_RATE_LIMIT_REQUESTS = '2000'
docker compose --profile benchmark -f deploy/compose.yaml up --build --wait --wait-timeout 180
uv run python scripts/benchmark_phase2.py
docker compose --profile benchmark -f deploy/compose.yaml stop redis
uv run python scripts/benchmark_phase2.py --redis-outage --output docs/benchmark-redis-outage.json
docker compose --profile benchmark -f deploy/compose.yaml down --timeout 15
```

Run `docker compose ... down` in a `finally` block if automating the sequence. The development
key is read from `SWITCHBOARD_API_KEY` and is never written to the data files. Results will vary
with host load, Docker scheduling, client runtime, and Redis condition. The cache hit path avoids a
mock upstream call; it does not make mock inference or any real model faster.

## Guarded semantic fixture path measurement

Measured on 2026-11-05 against acceptance code commit `31328ff` on Windows x86-64 with 20
logical CPUs, Docker Desktop, one Uvicorn gateway worker, Redis, Qdrant, and the pinned local
embedding worker. [`semantic-benchmark-results.json`](semantic-benchmark-results.json) contains
all 90 client-observed durations. `scripts/benchmark_semantic_cache.py` made three sequential runs
of ten buffered requests per case for one synthetic tenant. It warmed the static `stack` source
before timing. Provider requests used unique `mock-v1` prompts and were exact-cache misses; exact
requests reused the source prompt; semantic requests paraphrased it and verified the semantic-hit
header. The workload ID prevents accidental provider-key warming across repeated script runs.
Each duration spans HTTP POST through the complete response body; p50, p95, and p99 are nearest-rank
percentiles. Requests were interleaved by case; these observations do not isolate component cost.

| Local path | Requests | p50 ms | p95 ms | p99 ms | HTTP errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Provider, unique `mock-v1` requests | 30 | 6.795 | 9.361 | 10.786 | 0 |
| Warmed exact Redis hit | 30 | 3.952 | 5.791 | 7.116 | 0 |
| Guarded semantic fixture hit | 30 | 14.479 | 20.058 | 83.759 | 0 |

The semantic path was slower than the deterministic mock provider on this host because it embeds
each eligible request. These samples do not estimate real-provider latency, answer quality, token
cost, fleet throughput, or savings. Reproduce after setting `SWITCHBOARD_API_KEY` to the synthetic
key used in the Compose tenant digest and enabling both optional profiles:

```powershell
$env:SWITCHBOARD_SEMANTIC_CACHE_ENABLED = 'true'
$env:SWITCHBOARD_RATE_LIMIT_REQUESTS = '1000'
docker compose --profile embedding --profile semantic -f deploy/compose.yaml up --build --wait --wait-timeout 240
uv run python scripts/benchmark_semantic_cache.py --runs 3 --requests 10
docker compose --profile embedding --profile semantic -f deploy/compose.yaml down --timeout 15
```

The README shows how to set a development tenant digest; Compose requires it in the same shell.
