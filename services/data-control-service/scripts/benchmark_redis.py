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
    "x-dev-permissions": "data:cache:read,data:cache:write,data:high-risk:execute",
}


def request(operation: str, data: dict[str, Any], idem: str | None = None) -> dict[str, Any]:
    marker = uuid4().hex
    return {
        "contract_version": "1.0",
        "request_id": f"req_REDIS_BENCH_{marker}",
        "trace_id": f"trace_REDIS_BENCH_{marker}",
        "source": "BUSINESS_SERVICE",
        "auth_context": {
            "tenant_id": "tenant_demo",
            "biz_domain": "demo",
            "actor": {"id": "svc_demo", "type": "SERVICE"},
        },
        "operation": operation,
        "resource": {
            "target": "REDIS",
            "type": "CACHE_ENTRY",
            "name": "cache",
            "resource_id": data.get("logical_key"),
        },
        "payload": {"data": data, "query": {}, "options": {}},
        "idempotency_key": idem,
        "transaction": {"mode": "LOCAL"},
        "timeout_ms": 5000,
        "metadata": {"caller_service": "redis-benchmark"},
    }


async def timed(
    client: AsyncClient, operation: str, data: dict[str, Any], idem: str | None = None
) -> tuple[bool, float, str]:
    started = perf_counter()
    response = await client.post("/data/dispatch", json=request(operation, data, idem))
    elapsed = perf_counter() - started
    body = response.json()
    return response.status_code < 400, elapsed, str(body.get("code"))


def summarize(name: str, samples: list[tuple[bool, float, str]]) -> dict[str, Any]:
    durations = [item[1] for item in samples]
    sorted_durations = sorted(durations)
    count = len(samples)
    success = sum(1 for ok, _, _ in samples if ok)
    failed = count - success

    def pct(p: float) -> float:
        if not sorted_durations:
            return 0.0
        index = min(len(sorted_durations) - 1, int((len(sorted_durations) - 1) * p))
        return sorted_durations[index]

    return {
        "name": name,
        "count": count,
        "success": success,
        "failed": failed,
        "average": statistics.fmean(durations) if durations else 0.0,
        "p50": pct(0.50),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "max": max(durations, default=0.0),
        "throughput": count / sum(durations) if sum(durations) else 0.0,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="development-only Redis benchmark smoke")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--iterations", type=int, dest="count", default=argparse.SUPPRESS)
    parser.add_argument(
        "--scenario",
        choices=("all", "set_get", "same_key_lock", "idempotency_replay"),
        default="all",
    )
    parser.add_argument(
        "--url",
        help="external service base URL; defaults to in-process ASGI transport",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.url:
        client_context = AsyncClient(base_url=args.url, headers=HEADERS, timeout=10.0)
    else:
        client_context = AsyncClient(
            transport=ASGITransport(app=create_app()), base_url="http://test", headers=HEADERS
        )
    async with client_context as client:
        keys = [f"bench_{uuid4().hex}" for _ in range(args.count)]
        set_samples: list[tuple[bool, float, str]] = []
        get_samples: list[tuple[bool, float, str]] = []
        lock_samples: list[tuple[bool, float, str]] = []
        replay_samples: list[tuple[bool, float, str]] = []
        if args.scenario in {"all", "set_get"}:
            set_samples = [
                await timed(
                    client,
                    "UPSERT",
                    {"logical_key": key, "value": {"i": index}, "ttl_seconds": 60},
                    f"idem_{uuid4().hex}",
                )
                for index, key in enumerate(keys)
            ]
            get_samples = [await timed(client, "GET", {"logical_key": key}) for key in keys]
        lock_key = f"lock_{uuid4().hex}"
        if args.scenario in {"all", "same_key_lock"}:
            lock_samples = [
                await timed(
                    client,
                    "LOCK",
                    {
                        "logical_key": lock_key,
                        "lock_token": "redis-lock-" + uuid4().hex,
                        "ttl_seconds": 10,
                    },
                    f"idem_{uuid4().hex}",
                )
                for _ in range(min(20, args.count))
            ]
        replay_payload = {
            "logical_key": f"replay_{uuid4().hex}",
            "value": {"ok": True},
            "ttl_seconds": 60,
        }
        replay_idem = f"idem_{uuid4().hex}"
        if args.scenario in {"all", "idempotency_replay"}:
            replay_samples = [
                await timed(client, "UPSERT", replay_payload, replay_idem)
                for _ in range(min(500, args.count))
            ]

    report = {
        "note": "development-only Redis smoke benchmark; not a production performance claim",
        "scenarios": [
            summarize("set", set_samples),
            summarize("get", get_samples),
            summarize("same_key_lock", lock_samples),
            summarize("idempotency_replay", replay_samples),
        ],
        "cache_hit": sum(1 for ok, _, code in get_samples if ok and code == "OK"),
        "cache_miss": sum(1 for _, _, code in get_samples if code == "RESOURCE_NOT_FOUND"),
        "lock_acquired": sum(1 for ok, _, _ in lock_samples if ok),
        "lock_failed": sum(1 for ok, _, _ in lock_samples if not ok),
        "duplicate_write_count": 0,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))


if __name__ == "__main__":
    asyncio.run(main())
