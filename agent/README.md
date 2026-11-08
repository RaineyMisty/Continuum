# Agent — AI 执行模块

负责模型调用、多轮改写、固定验证、暂停、恢复、分叉与导出。

- `engine.py`：检查点状态机。
- `providers.py`：真实模型与离线 mock。
- `workspace.py`、`validation.py`：安全路径校验、文件修改和验证副本。
- `storage.py`：本地执行检查点；这是恢复基础设施，不是数据库研究算法。
- `cli.py`、`__main__.py`：`continuum` / `python -m agent` 入口。
- `tests/`：执行、故障恢复和数据库接口集成测试。

仅依赖 `memory.context` 中的数据库协议，不依赖 demo 的业务实现。通过输入路径读取任意支持的 Python 项目。

在仓库根目录运行 `python -m pytest -q`。具体命令见根 README；恢复协议见 [ARCHITECTURE.md](ARCHITECTURE.md)。
