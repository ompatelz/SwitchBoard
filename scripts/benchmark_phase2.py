"""Small real-HTTP benchmark for the deterministic Phase 2 gateway paths."""

import argparse
import asyncio
import json
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

CASES = ("mock_direct", "gateway_uncached", "cache_miss", "cache_hit", "concurrency_four")


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile of measured milliseconds."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def metric(text: str, result: str) -> float:
    prefix = f'switchboard_cache_operations_total{{result="{result}"}} '
    return next(
        (float(line[len(prefix) :]) for line in text.splitlines() if line.startswith(prefix)), 0.0
    )


async def run_case(
    client: httpx.AsyncClient,
    *,
    url: str,
    key: str | None,
    case: str,
    run: int,
    count: int,
    concurrency: int,
    prefix: str,
) -> dict[str, Any]:
    barrier = asyncio.Semaphore(concurrency)
    timings: list[float] = []
    statuses: list[int] = []
    content = f"{prefix}-{case}-{run}"

    async def one(index: int) -> None:
        async with barrier:
            prompt = content if case == "cache_hit" else f"{content}-{index}"
            headers = {"Authorization": f"Bearer {key}"} if key is not None else {}
            started = time.perf_counter()
            response = await client.post(
                f"{url}/v1/chat/completions",
                headers=headers,
                json={"model": "mock-v1", "messages": [{"role": "user", "content": prompt}]},
            )
            timings.append((time.perf_counter() - started) * 1000)
            statuses.append(response.status_code)
            if response.status_code == 200:
                assert response.json()["object"] == "chat.completion"

    if case == "cache_hit":
        warm = await client.post(
            f"{url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "mock-v1", "messages": [{"role": "user", "content": content}]},
        )
        if warm.status_code != 200:
            raise RuntimeError(f"cache warmup failed with HTTP {warm.status_code}")
    started = time.perf_counter()
    await asyncio.gather(*(one(index) for index in range(count)))
    wall = time.perf_counter() - started
    return {
        "case": case,
        "run": run,
        "requests": count,
        "concurrency": concurrency,
        "errors": sum(status != 200 for status in statuses),
        "status_counts": {str(status): statuses.count(status) for status in sorted(set(statuses))},
        "p50_ms": round(percentile(timings, 0.50), 3),
        "p95_ms": round(percentile(timings, 0.95), 3),
        "p99_ms": round(percentile(timings, 0.99), 3),
        "throughput_rps": round(count / wall, 3),
        "wall_seconds": round(wall, 3),
        "latencies_ms": [round(value, 3) for value in timings],
    }


async def benchmark(args: argparse.Namespace) -> dict[str, Any]:
    key = os.environ.get("SWITCHBOARD_API_KEY")
    if not key:
        raise RuntimeError("set SWITCHBOARD_API_KEY to the development key")
    prefix = f"benchmark-{uuid.uuid4().hex[:12]}"
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=10, limits=httpx.Limits(max_connections=32)) as client:
        before = {
            name: await client.get(f"{url}/metrics")
            for name, url in (("cached", args.cached_url), ("uncached", args.uncached_url))
        }
        if any(response.status_code != 200 for response in before.values()):
            raise RuntimeError("gateway metrics endpoint is unavailable")
        for case in CASES:
            url = (
                args.mock_url
                if case == "mock_direct"
                else args.uncached_url
                if case == "gateway_uncached"
                else args.cached_url
            )
            for run in range(1, args.runs + 1):
                result = await run_case(
                    client,
                    url=url,
                    key=None if case == "mock_direct" else key,
                    case=case,
                    run=run,
                    count=args.requests,
                    concurrency=args.concurrency if case == "concurrency_four" else 1,
                    prefix=prefix,
                )
                results.append(result)
                print(
                    f"{case} run {run}: {result['errors']} errors, "
                    f"p95={result['p95_ms']} ms, {result['throughput_rps']} req/s"
                )
        after = {
            name: await client.get(f"{url}/metrics")
            for name, url in (("cached", args.cached_url), ("uncached", args.uncached_url))
        }
    deltas = {
        name: {
            outcome: int(metric(after[name].text, outcome) - metric(before[name].text, outcome))
            for outcome in ("hit", "miss", "bypass", "write", "error")
        }
        for name in before
    }
    if any(result["errors"] for result in results):
        raise RuntimeError("benchmark contained non-200 responses; inspect status_counts")
    expected = args.runs * args.requests
    if deltas["cached"]["hit"] < expected or deltas["cached"]["miss"] < 2 * expected:
        raise RuntimeError("cache hit/miss metrics did not match the workload")
    if deltas["uncached"]["bypass"] < expected:
        raise RuntimeError("uncached gateway did not bypass the cache")
    return {
        "workload": {
            "runs": args.runs,
            "requests_per_case_per_run": args.requests,
            "controlled_concurrency": args.concurrency,
            "prompt_prefix": prefix,
            "provider": "deterministic mock, no configured response delay",
            "percentile_method": "nearest rank",
        },
        "results": results,
        "cache_metric_deltas": deltas,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-url", default="http://127.0.0.1:8001")
    parser.add_argument("--cached-url", default="http://127.0.0.1:8000")
    parser.add_argument("--uncached-url", default="http://127.0.0.1:8002")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output", type=Path, default=Path("docs/benchmark-data.json"))
    args = parser.parse_args()
    if min(args.runs, args.requests, args.concurrency) < 1:
        parser.error("runs, requests, and concurrency must be positive")
    data = asyncio.run(benchmark(args))
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
