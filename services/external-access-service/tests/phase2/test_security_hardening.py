import logging

from external_access_service.infrastructure.observability.redaction import redact


def test_sensitive_data_masker_covers_phase2_terms() -> None:
    masked = redact(
        {
            "access_key": "ak",
            "secret": "s",
            "authorization": "Bearer token",
            "signature": "sig",
            "request_body": "legal sensitive data",
        }
    )
    assert masked["access_key"] == "***REDACTED***"
    assert masked["secret"] == "***REDACTED***"
    assert masked["authorization"] == "***REDACTED***"
    assert masked["signature"] == "***REDACTED***"


def test_logs_do_not_include_secret_values(caplog) -> None:
    logger = logging.getLogger("external-access-test")
    with caplog.at_level(logging.INFO):
        logger.info("safe event %s", redact({"token": "bearer token", "secret": "secret"}))
    text = caplog.text.lower()
    assert "bearer token" not in text
    assert "'secret': 'secret'" not in text
