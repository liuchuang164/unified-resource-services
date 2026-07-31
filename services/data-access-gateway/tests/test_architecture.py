from pathlib import Path


def test_gateway_has_no_minio_sdk_or_business_idempotency_repository() -> None:
    service_root = Path(__file__).parents[1]
    pyproject = (service_root / "pyproject.toml").read_text()
    source = "\n".join(path.read_text() for path in (service_root / "src").rglob("*.py"))
    assert '"minio' not in pyproject.lower()
    assert "from minio import" not in source
    assert "IdempotencyRepository" not in source
    assert "idempotency_repository" not in source
