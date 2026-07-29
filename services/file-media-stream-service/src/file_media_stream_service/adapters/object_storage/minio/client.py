from minio import Minio


def create_minio_client(
    endpoint: str,
    access_key: str,
    secret_key: str,
    *,
    secure: bool,
) -> Minio:
    """Create a client without retaining credentials outside the SDK."""
    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
