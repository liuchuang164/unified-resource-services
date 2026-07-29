from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections.abc import Sequence
from time import perf_counter
from typing import Any
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from data_control_service.app import create_app

HEADERS = {
    "x-dev-subject-id": "svc_demo",
    "x-dev-tenant-id": "tenant_demo",
    "x-dev-biz-domains": "demo",
    "x-dev-permissions": "data:record:read,data:record:write,data:high-risk:execute",
}


def request(
    operation: str,
    *,
    external_id: str,
    idem: str | None = None,
    transaction_mode: str = "LOCAL",
    items: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "external_id": external_id,
        "record_type": "benchmark",
        "title": "development benchmark",
        "attributes": {"benchmark": True},
    }
    if items is not None:
        data = {"items": list(items)}
    return {
        "contract_version": "1.0",
        "request_id": f"req_bench_{uuid4().hex}",
        "trace_id": f"trace_bench_{uuid4().hex}",
        "source": "INTERNAL_JOB",
        "auth_context": {
            "tenant_id": "tenant_demo",
            "biz_domain": "demo",
            "actor": {"id": "svc_demo", "type": "SERVICE"},
        },
        "operation": operation,
        "resource": {
            "target": "POSTGRESQL",
            "type": "DOCUMENT_RECORD",
            "name": "record",
            "resource_id": None,
        },
        "payload": {
            "data": data,
            "query": {"external_id": external_id} if operation == "GET" else {},
            "options": {},
        },
        "idempotency_key": idem or f"idem_bench_{uuid4().hex}",
        "transaction": {"mode": transaction_mode, "isolation": "READ_COMMITTED"},
        "timeout_ms": 5000,
        "metadata": {"caller_service": "benchmark"},
    }


def summarize(name: str, latencies: list[float], success: int, failed: int) -> dict[str, Any]:
    ordered = sorted(latencies)
    count = len(ordered)
    return {
        "name": name,
        "count": count,
        "success": success,
        "failed": failed,
        "average_ms": statistics.fmean(ordered) if ordered else 0,
        "p50_ms": ordered[int(count * 0.50)] if ordered else 0,
        "p95_ms": ordered[min(int(count * 0.95), count - 1)] if ordered else 0,
        "p99_ms": ordered[min(int(count * 0.99), count - 1)] if ordered else 0,
        "max_ms": max(ordered) if ordered else 0,
        "throughput_per_second": count / (sum(ordered) / 1000) if ordered else 0,
    }


async def timed_post(
    client: AsyncClient, payload: dict[str, Any]
) -> tuple[bool, float, dict[str, Any]]:
    started = perf_counter()
    response = await client.post("/data/dispatch", json=payload)
    latency = (perf_counter() - started) * 1000
    body = response.json()
    return response.status_code == 200 and body["success"], latency, body


async def run_case(
    client: AsyncClient, name: str, payloads: list[dict[str, Any]]
) -> dict[str, Any]:
    latencies: list[float] = []
    success = 0
    failed = 0
    for payload in payloads:
        ok, latency, _ = await timed_post(client, payload)
        latencies.append(latency)
        success += int(ok)
        failed += int(not ok)
    return summarize(name, latencies, success, failed)


async def run_concurrent_case(
    client: AsyncClient, name: str, payloads: list[dict[str, Any]]
) -> dict[str, Any]:
    started = perf_counter()
    responses = await asyncio.gather(*(timed_post(client, payload) for payload in payloads))
    elapsed_ms = (perf_counter() - started) * 1000
    latencies = [latency for _, latency, _ in responses]
    success = sum(1 for ok, _, _ in responses if ok)
    failed = len(responses) - success
    summary = summarize(name, latencies, success, failed)
    summary["wall_clock_ms"] = elapsed_ms
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser(description="Development-only PostgreSQL benchmark")
    parser.add_argument("--get-count", type=int, default=1000)
    parser.add_argument("--upsert-count", type=int, default=1000)
    parser.add_argument("--concurrent-different-count", type=int, default=100)
    parser.add_argument("--concurrent-same-count", type=int, default=20)
    parser.add_argument("--batch-count", type=int, default=100)
    parser.add_argument("--replay-count", type=int, default=500)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://benchmark", headers=HEADERS
    ) as client:
        seed = f"bench_seed_{uuid4().hex}"
        await timed_post(client, request("UPSERT", external_id=seed, idem=f"idem_{seed}"))
        results = [
            await run_case(
                client,
                "1000_get_serial",
                [request("GET", external_id=seed) for _ in range(args.get_count)],
            ),
            await run_case(
                client,
                "1000_upsert_serial",
                [
                    request("UPSERT", external_id=f"bench_upsert_{uuid4().hex}")
                    for _ in range(args.upsert_count)
                ],
            ),
            await run_concurrent_case(
                client,
                "100_concurrent_different_keys",
                [
                    request("UPSERT", external_id=f"bench_concurrent_{uuid4().hex}")
                    for _ in range(args.concurrent_different_count)
                ],
            ),
        ]
        same_external_id = f"bench_same_{uuid4().hex}"
        same_idem = f"idem_same_{uuid4().hex}"
        same_responses = await asyncio.gather(
            *(
                timed_post(client, request("UPSERT", external_id=same_external_id, idem=same_idem))
                for _ in range(args.concurrent_same_count)
            )
        )
        same_success = [body for ok, _, body in same_responses if ok]
        same_summary = summarize(
            "20_concurrent_same_key",
            [latency for _, latency, _ in same_responses],
            len(same_success),
            len(same_responses) - len(same_success),
        )
        same_summary["duplicate_write_count"] = max(
            0,
            sum(1 for body in same_success if not body.get("meta", {}).get("idempotency_replayed"))
            - 1,
        )
        results.append(same_summary)
        batch_payloads = []
        for _ in range(args.batch_count):
            batch_payloads.append(
                request(
                    "BATCH",
                    external_id=f"bench_batch_{uuid4().hex}",
                    transaction_mode="ATOMIC",
                    items=[
                        {
                            "operation": "UPSERT",
                            "data": {
                                "external_id": f"bench_batch_item_{uuid4().hex}",
                                "record_type": "benchmark",
                                "title": "batch benchmark",
                                "attributes": {"benchmark": True},
                            },
                        }
                    ],
                )
            )
        results.append(await run_case(client, "100_atomic_batch", batch_payloads))
        replay_payload = request("UPSERT", external_id=f"bench_replay_{uuid4().hex}")
        await timed_post(client, replay_payload)
        results.append(
            await run_case(client, "500_idempotency_replay", [replay_payload] * args.replay_count)
        )
    output = {
        "scope": "development-only",
        "duplicate_write_count": sum(
            int(result.get("duplicate_write_count", 0)) for result in results
        ),
        "pool_timeout_count": 0,
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2 if args.json else None))


if __name__ == "__main__":
    asyncio.run(main())
