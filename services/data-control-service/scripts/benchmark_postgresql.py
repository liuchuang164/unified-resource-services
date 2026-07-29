from __future__ import annotations

import argparse
import asyncio
import json
import statistics
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


def request(operation: str, *, external_id: str, idem: str | None = None) -> dict[str, Any]:
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
            "data": {
                "external_id": external_id,
                "record_type": "benchmark",
                "title": "development benchmark",
                "attributes": {"benchmark": True},
            },
            "query": {"external_id": external_id} if operation == "GET" else {},
            "options": {},
        },
        "idempotency_key": idem or f"idem_bench_{uuid4().hex}",
        "transaction": {"mode": "LOCAL", "isolation": "READ_COMMITTED"},
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


async def timed_post(client: AsyncClient, payload: dict[str, Any]) -> tuple[bool, float]:
    started = perf_counter()
    response = await client.post("/data/dispatch", json=payload)
    return response.status_code == 200 and response.json()["success"], (
        perf_counter() - started
    ) * 1000


async def run_case(
    client: AsyncClient, name: str, payloads: list[dict[str, Any]]
) -> dict[str, Any]:
    latencies: list[float] = []
    success = 0
    failed = 0
    for payload in payloads:
        ok, latency = await timed_post(client, payload)
        latencies.append(latency)
        success += int(ok)
        failed += int(not ok)
    return summarize(name, latencies, success, failed)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Development-only PostgreSQL benchmark")
    parser.add_argument("--serial-count", type=int, default=1000)
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
                "serial_get",
                [request("GET", external_id=seed) for _ in range(args.serial_count)],
            ),
            await run_case(
                client,
                "serial_upsert",
                [
                    request("UPSERT", external_id=f"bench_upsert_{uuid4().hex}")
                    for _ in range(args.serial_count)
                ],
            ),
        ]
        replay_payload = request("UPSERT", external_id=f"bench_replay_{uuid4().hex}")
        await timed_post(client, replay_payload)
        results.append(
            await run_case(client, "idempotency_replay", [replay_payload] * args.replay_count)
        )
    output = {"scope": "development-only", "results": results}
    print(json.dumps(output, ensure_ascii=False, indent=2 if args.json else None))


if __name__ == "__main__":
    asyncio.run(main())
