from data_control_service.application.audit_service import redact


def test_redact_recursively_removes_secret_values() -> None:
    value = {
        "Authorization": "Bearer test",
        "nested": {"password": "test-password", "safe": "ok"},
        "items": [{"token": "test-token"}],
    }
    assert redact(value) == {
        "Authorization": "***REDACTED***",
        "nested": {"password": "***REDACTED***", "safe": "ok"},
        "items": [{"token": "***REDACTED***"}],
    }
