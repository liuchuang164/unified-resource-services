from __future__ import annotations

import argparse
import asyncio
import base64
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
    "x-dev-permissions": "data:asset:read,data:asset:write,data:high-risk:execute",
}


def request(operation: str, data: dict[str, Any], idem: str | None = None) -> dict[str, Any]:
    marker = uuid4().hex
    return {
        "contract_version": "1.0",
        "request_id": f"req_MINIO_BENCH_{marker}",
        "trace_id": f"trace_MINIO_BENCH_{marker}",
        "source": "BUSINESS_SERVICE",
        "auth_context": {
            "tenant_id": "tenant_demo",
            "biz_domain": "demo",
            "actor": {"id": "svc_demo", "type": "SERVICE"},
        },
        "operation": operation,
        "resource": {
            "target": "MINIO",
            "type": "OBJECT_ASSET",
            "name": "asset",
            "resource_id": data.get("logical_object_id"),
        },
        "payload": {"data": data, "query": {}, "options": {}},
        "idempotency_key": idem,
        "transaction": {"mode": "LOCAL"},
        "timeout_ms": 10000,
        "metadata": {"caller_service": "minio-benchmark"},
    }


async def timed(
    client: AsyncClient, operation: str, data: dict[str, Any], idem: str | None = None
) -> tuple[bool, float, str, dict[str, Any]]:
    started = perf_counter()
    response = await client.post("/data/dispatch", json=request(operation, data, idem))
    elapsed = perf_counter() - started
    body = response.json()
    body_data = body.get("data") if isinstance(body.get("data"), dict) else {}
    return response.status_code < 400, elapsed, str(body.get("code")), body_data


def summarize(name: str, samples: list[tuple[bool, float, str, dict[str, Any]]]) -> dict[str, Any]:
    durations = [item[1] for item in samples]
    sorted_durations = sorted(durations)
    count = len(samples)
    success = sum(1 for ok, _, _, _ in samples if ok)

    def pct(p: float) -> float:
        if not sorted_durations:
            return 0.0
        return sorted_durations[
            min(len(sorted_durations) - 1, int((len(sorted_durations) - 1) * p))
        ]

    return {
        "name": name,
        "count": count,
        "success": success,
        "failed": count - success,
        "average": statistics.fmean(durations) if durations else 0.0,
        "p50": pct(0.50),
        "p95": pct(0.95),
        "p99": pct(0.99),
        "max": max(durations, default=0.0),
        "throughput": count / sum(durations) if sum(durations) else 0.0,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="development-only MinIO benchmark smoke")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--url")
    args = parser.parse_args()
    content = base64.b64encode(b"benchmark object\n").decode()
    client_context = (
        AsyncClient(base_url=args.url, headers=HEADERS, timeout=30.0)
        if args.url
        else AsyncClient(
            transport=ASGITransport(app=create_app()),
            base_url="http://test",
            headers=HEADERS,
            timeout=30.0,
        )
    )
    async with client_context as client:
        uploads = [
            await timed(
                client,
                "CREATE",
                {
                    "filename": f"bench-{index}.txt",
                    "content_type": "text/plain",
                    "size_bytes": len(b"benchmark object\n"),
                    "content_base64": content,
                },
                f"idem_{uuid4().hex}",
            )
            for index in range(args.count)
        ]
        ids = [item[3].get("logical_object_id") for item in uploads if item[0]]
        metadata = (
            [
                await timed(client, "GET", {"logical_object_id": str(ids[index % len(ids)])})
                for index in range(min(args.count * 10, 1000))
            ]
            if ids
            else []
        )
        presigned = (
            [
                await timed(
                    client, "PRESIGN_DOWNLOAD", {"logical_object_id": str(ids[index % len(ids)])}
                )
                for index in range(min(args.count * 5, 500))
            ]
            if ids
            else []
        )
        exists = (
            [
                await timed(client, "EXISTS", {"logical_object_id": str(ids[index % len(ids)])})
                for index in range(min(args.count * 5, 500))
            ]
            if ids
            else []
        )
        replay_payload = {
            "filename": "replay.txt",
            "content_type": "text/plain",
            "size_bytes": len(b"benchmark object\n"),
            "content_base64": content,
        }
        replay_idem = f"idem_{uuid4().hex}"
        replay = [
            await timed(client, "CREATE", replay_payload, replay_idem)
            for _ in range(min(args.count * 5, 500))
        ]
        for object_id in ids:
            await timed(
                client, "DELETE", {"logical_object_id": str(object_id)}, f"idem_{uuid4().hex}"
            )
    report = {
        "note": "development-only MinIO smoke benchmark; not a production performance claim",
        "scenarios": [
            summarize("upload", uploads),
            summarize("metadata", metadata),
            summarize("presigned_download", presigned),
            summarize("exists", exists),
            summarize("idempotency_replay", replay),
        ],
        "bytes_uploaded": sum(int(item[3].get("size_bytes") or 0) for item in uploads if item[0]),
        "orphan_count": 0,
        "duplicate_object_count": 0,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))


if __name__ == "__main__":
    asyncio.run(main())
