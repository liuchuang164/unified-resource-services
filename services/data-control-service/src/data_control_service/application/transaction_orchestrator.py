from dataclasses import replace

from data_control_service.adapters.base import DataAdapter
from data_control_service.contracts.enums import Operation, TransactionMode
from data_control_service.domain.exceptions import DataControlError
from data_control_service.domain.models import AdapterCommand, AdapterResult, ExecutionContext


class TransactionOrchestrator:
    async def execute(
        self,
        *,
        adapter: DataAdapter,
        command: AdapterCommand,
        context: ExecutionContext,
        mode: TransactionMode,
    ) -> AdapterResult:
        if mode in {TransactionMode.NONE, TransactionMode.LOCAL}:
            return await adapter.execute(command, context)
        if mode == TransactionMode.ATOMIC:
            return await self._execute_atomic(adapter, command, context)
        if mode == TransactionMode.BEST_EFFORT:
            return await self._execute_best_effort(adapter, command, context)
        raise DataControlError("TRANSACTION_NOT_SUPPORTED")

    async def _execute_atomic(
        self, adapter: DataAdapter, command: AdapterCommand, context: ExecutionContext
    ) -> AdapterResult:
        if not adapter.capabilities().supports_atomic_transaction:
            raise DataControlError("TRANSACTION_NOT_SUPPORTED")
        transaction = await adapter.begin(context)
        try:
            if command.operation == Operation.BATCH:
                results = []
                for item_command in self._item_commands(command):
                    results.append(await adapter.execute(item_command, context))
                await transaction.commit()
                return AdapterResult(
                    status="OK",
                    data={
                        "total": len(results),
                        "succeeded": len(results),
                        "failed": 0,
                        "items": [
                            {"index": index, "success": True, "code": "OK", "data": result.data}
                            for index, result in enumerate(results)
                        ],
                    },
                    affected_count=sum(result.affected_count for result in results),
                )
            result = await adapter.execute(command, context)
            await transaction.commit()
            return result
        except Exception:
            await transaction.rollback()
            raise

    async def _execute_best_effort(
        self, adapter: DataAdapter, command: AdapterCommand, context: ExecutionContext
    ) -> AdapterResult:
        if command.operation != Operation.BATCH:
            return await adapter.execute(command, context)
        items = []
        succeeded = 0
        failed = 0
        for index, item_command in enumerate(self._item_commands(command)):
            try:
                result = await adapter.execute(item_command, context)
                succeeded += 1
                items.append(
                    {
                        "index": index,
                        "success": True,
                        "code": "OK",
                        "message": "success",
                        "data": result.data,
                    }
                )
            except DataControlError as exc:
                failed += 1
                items.append(
                    {
                        "index": index,
                        "success": False,
                        "code": exc.code,
                        "message": exc.message,
                        "error": {
                            "category": exc.spec.category.value,
                            "retryable": exc.spec.retryable,
                        },
                    }
                )
        return AdapterResult(
            status="PARTIAL_FAILURE" if failed else "OK",
            data={"total": len(items), "succeeded": succeeded, "failed": failed, "items": items},
            affected_count=succeeded,
        )

    @staticmethod
    def _item_commands(command: AdapterCommand) -> list[AdapterCommand]:
        items = command.validated_payload.get("data", {}).get("items", [])
        commands = []
        for item in items:
            operation = Operation(item.get("operation", Operation.UPSERT.value))
            item_payload = {
                **command.validated_payload,
                "data": item.get("data", item),
                "resource_id": item.get("resource_id") or item.get("data", {}).get("id"),
            }
            commands.append(replace(command, operation=operation, validated_payload=item_payload))
        return commands
