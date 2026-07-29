# Phase 0 测试报告

执行环境：macOS arm64，Python 3.12.9。

最终结果：

| Gate | Command | Result |
|---|---|---|
| Ruff lint | `.venv/bin/ruff check .` | passed, no errors |
| Ruff format | `.venv/bin/ruff format --check .` | passed, 63 files formatted |
| Mypy | `.venv/bin/mypy src` | passed, 50 source files |
| Pytest | `.venv/bin/pytest` | 57 passed, 0 failed, 0 skipped |
| Coverage | `.venv/bin/pytest --cov=src --cov-report=term-missing` | 93.72% total |

核心模块覆盖率：Domain 91–100%，Application DTO 100%，Application Use Cases 89%，
Unified Entry 94%，Security 97%。

已知的第三方警告：FastAPI 0.140.13 / Starlette 1.3.1 的 `TestClient` 对 httpx 发出迁移
deprecation warning；不影响测试断言，后续依赖窗口统一处理，Phase 0 不做无关升级。
