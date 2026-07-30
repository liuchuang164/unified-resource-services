from enum import StrEnum


class Source(StrEnum):
    BUSINESS_SERVICE = "BUSINESS_SERVICE"
    ONTOLOGY_SERVICE = "ONTOLOGY_SERVICE"
    DATA_ACCESS_GATEWAY = "DATA_ACCESS_GATEWAY"
    INTERNAL_JOB = "INTERNAL_JOB"


class SubjectType(StrEnum):
    USER = "USER"
    SERVICE = "SERVICE"
    AGENT = "AGENT"
    JOB = "JOB"


class Operation(StrEnum):
    GET = "GET"
    EXISTS = "EXISTS"
    LIST = "LIST"
    PRESIGN_UPLOAD = "PRESIGN_UPLOAD"
    UPLOAD_COMPLETE = "UPLOAD_COMPLETE"
    PRESIGN_DOWNLOAD = "PRESIGN_DOWNLOAD"
    SEARCH = "SEARCH"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    UPSERT = "UPSERT"
    DELETE = "DELETE"
    BATCH = "BATCH"
    LOCK = "LOCK"
    UNLOCK = "UNLOCK"


class DataTarget(StrEnum):
    POSTGRESQL = "POSTGRESQL"
    MINIO = "MINIO"
    REDIS = "REDIS"
    NEO4J = "NEO4J"
    MILVUS = "MILVUS"
    TIMESCALEDB = "TIMESCALEDB"


class DataClass(StrEnum):
    TRANSACTIONAL = "TRANSACTIONAL"
    OBJECT = "OBJECT"
    CACHE = "CACHE"
    GRAPH = "GRAPH"
    VECTOR = "VECTOR"
    TIME_SERIES = "TIME_SERIES"


class TransactionMode(StrEnum):
    NONE = "NONE"
    LOCAL = "LOCAL"
    BEST_EFFORT = "BEST_EFFORT"
    ATOMIC = "ATOMIC"


WRITE_OPERATIONS = {
    Operation.CREATE,
    Operation.UPDATE,
    Operation.UPSERT,
    Operation.DELETE,
    Operation.BATCH,
    Operation.LOCK,
    Operation.UNLOCK,
    Operation.PRESIGN_UPLOAD,
    Operation.UPLOAD_COMPLETE,
}
