import pytest

from external_access_service.domain.errors import OperationNotFound
from external_access_service.domain.operations import OperationRegistry
from external_access_service.interfaces.eag.gateway import ACTION_OPERATION


def test_operation_registry_filters_by_tenant_and_biz_domain() -> None:
    registry = OperationRegistry()
    assert len(registry.list("tenant_A", "LEGAL")) == 4
    assert registry.list("tenant_A", "FINANCE") == []


def test_operation_registry_unknown_operation() -> None:
    with pytest.raises(OperationNotFound):
        OperationRegistry().get("MISSING")


def test_tool_mapping_uses_canonical_operations() -> None:
    assert ACTION_OPERATION["legal_consult"] == "ALI_FARUI_LEGAL_CONSULT"
    assert ACTION_OPERATION["law_search"] == "ALI_FARUI_LAW_SEARCH"
