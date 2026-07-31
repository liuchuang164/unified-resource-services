from functools import lru_cache

from data_access_gateway.auth import CapabilityTokenVerifier
from data_access_gateway.client import HttpDataControlClient
from data_access_gateway.config import Settings
from data_access_gateway.minio_tool import MINIO_TOOL
from data_access_gateway.registry import ToolRegistry
from data_access_gateway.service import ToolExecutionService


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_verifier() -> CapabilityTokenVerifier:
    return CapabilityTokenVerifier(get_settings())


@lru_cache
def get_registry() -> ToolRegistry:
    return ToolRegistry([MINIO_TOOL])


@lru_cache
def get_data_control_client() -> HttpDataControlClient:
    return HttpDataControlClient(get_settings())


@lru_cache
def get_tool_execution_service() -> ToolExecutionService:
    return ToolExecutionService(get_registry(), get_data_control_client())


async def close_dependencies() -> None:
    if get_data_control_client.cache_info().currsize:
        await get_data_control_client().close()
    get_tool_execution_service.cache_clear()
    get_data_control_client.cache_clear()
