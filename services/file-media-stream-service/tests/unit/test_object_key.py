import pytest

from file_media_stream_service.domain.exceptions import InvalidObjectName
from file_media_stream_service.domain.services import generate_object_key, normalize_filename


def test_normalize_filename_and_generate_key() -> None:
    safe = normalize_filename("case evidence_01.pdf")
    assert safe == "case_evidence_01.pdf"
    assert (
        generate_object_key("tenant-a", "legal", "res-1", 1, safe)
        == "tenant/tenant-a/domain/legal/resource/res-1/1/case_evidence_01.pdf"
    )


@pytest.mark.parametrize(
    "filename",
    ["../secret", "/etc/passwd", r"..\\secret", "a/b.pdf", "a\x00.pdf", "．/secret"],  # noqa: RUF001
)
def test_path_traversal_and_unicode_confusion_rejected(filename: str) -> None:
    with pytest.raises(InvalidObjectName):
        normalize_filename(filename)


def test_filename_length_is_bounded() -> None:
    value = normalize_filename(f"{'a' * 220}.pdf")
    assert len(value) == 180
    assert value.endswith(".pdf")


def test_double_extension_is_rejected() -> None:
    with pytest.raises(InvalidObjectName):
        normalize_filename("payload.exe.pdf")


@pytest.mark.parametrize(
    "scope",
    ["../tenant", "tenant/a", "ｔenant", "", "a b"],  # noqa: RUF001
)
def test_unsafe_scope_rejected(scope: str) -> None:
    with pytest.raises(InvalidObjectName):
        generate_object_key(scope, "legal", "res-1", 1, "safe.pdf")
