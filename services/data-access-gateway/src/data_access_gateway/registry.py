from dataclasses import dataclass

from pydantic import BaseModel

from data_access_gateway.errors import GatewayError


@dataclass(frozen=True)
class ToolAction:
    name: str
    operation: str
    params_model: type[BaseModel]
    write: bool
    high_risk: bool = False


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    version: str
    description: str
    target: str
    resource_type: str
    resource_name: str
    actions: tuple[ToolAction, ...]


class ToolRegistry:
    def __init__(self, definitions: list[ToolDefinition]) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        for definition in definitions:
            if definition.name in self._definitions:
                raise ValueError(f"duplicate tool registration: {definition.name}")
            action_names = [action.name for action in definition.actions]
            if len(action_names) != len(set(action_names)):
                raise ValueError(f"duplicate action registration: {definition.name}")
            self._definitions[definition.name] = definition

    def get(self, tool_name: str) -> ToolDefinition:
        definition = self._definitions.get(tool_name)
        if definition is None:
            raise GatewayError("TOOL_NOT_FOUND")
        return definition

    def action(self, tool_name: str, action_name: str) -> tuple[ToolDefinition, ToolAction]:
        definition = self.get(tool_name)
        for action in definition.actions:
            if action.name == action_name:
                return definition, action
        raise GatewayError("TOOL_ACTION_NOT_SUPPORTED")

    def list_visible(self, allowed_tools: tuple[str, ...]) -> list[ToolDefinition]:
        allowed = set(allowed_tools)
        return [item for item in self._definitions.values() if item.name in allowed]
