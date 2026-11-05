"""Measure three local mock paths without attributing real-provider savings."""

import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import time
from pathlib import Path

import httpx


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(quantile * len(ordered)) - 1)], 3)


def completion(client: httpx.Client, model: str, prompt: str) -> httpx.Response:
    return client.post(
        "/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", default="http://127.0.0.1:8000")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--requests", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("docs/semantic-benchmark-results.json"))
    args = parser.parse_args()
    key = os.environ["SWITCHBOARD_API_KEY"]
    if args.runs < 1 or args.requests < 1:
        raise ValueError("runs and requests must be positive")
    cases: dict[str, list[float]] = {"provider": [], "exact": [], "semantic": []}
    with httpx.Client(
        base_url=args.gateway,
        headers={"Authorization": f"Bearer {key}"},
        timeout=30,
    ) as client:
        warm = completion(client, "static-definition-fixture-v1", "What is a stack?")
        warm.raise_for_status()
        for run in range(args.runs):
            for index in range(args.requests):
                for case, model, prompt in (
                    ("provider", "mock-v1", f"Uncached fixture request {run}-{index}"),
                    ("exact", "static-definition-fixture-v1", "What is a stack?"),
                    ("semantic", "static-definition-fixture-v1", "Define a stack?"),
                ):
                    start = time.perf_counter()
                    response = completion(client, model, prompt)
                    elapsed = (time.perf_counter() - start) * 1000
                    response.raise_for_status()
                    if case == "semantic":
                        if response.headers.get("X-Switchboard-Cache") != "semantic":
                            raise ValueError("semantic request was not a semantic hit")
                    elif response.headers.get("X-Switchboard-Cache") == "semantic":
                        raise ValueError("nonsemantic request unexpectedly used a semantic hit")
                    cases[case].append(elapsed)
    report = {
        "workload": "one synthetic tenant, one Uvicorn worker, sequential buffered requests",
        "runs": args.runs,
        "requests_per_case_per_run": args.requests,
        "host": {
            "system": platform.system(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
        "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "cases": {
            case: {
                "requests": len(values),
                "p50_ms": percentile(values, 0.50),
                "p95_ms": percentile(values, 0.95),
                "p99_ms": percentile(values, 0.99),
                "mean_ms": round(statistics.mean(values), 3),
                "samples_ms": [round(value, 3) for value in values],
                "http_errors": 0,
            }
            for case, values in cases.items()
        },
        "limitations": [
            "mock provider only; no paid-provider latency, cost, or answer-quality inference",
            "the semantic case embeds each request; fixture answer content is fixed",
            "sequential local loopback samples share one process and host",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                case: {key: value for key, value in result.items() if key != "samples_ms"}
                for case, result in report["cases"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
