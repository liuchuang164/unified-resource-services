from pathlib import Path


def test_domain_does_not_import_fastapi_or_infrastructure() -> None:
    root = Path("src/data_control_service/domain")
    content = "\n".join(path.read_text() for path in root.glob("*.py"))
    assert "fastapi" not in content
    assert "infrastructure" not in content


def test_api_does_not_access_registry_private_fields() -> None:
    api_content = "\n".join(
        path.read_text() for path in Path("src/data_control_service/api").rglob("*.py")
    )
    assert "._adapter_registry" not in api_content
