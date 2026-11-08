# Continuum — 可中断、可恢复的 Python 重构实验框架

Python 包和 CLI 保留 `ghostgraph` 名称。此版本实现旧代码输入/新代码输出、AI 多轮改写、验证、暂停、恢复和对照实验；SpacetimeDB 只保留接口，尚未实现数据库算法。

## 三个模块

1. **旧代码 / 新代码**：复制输入形成只读基线；先验证旧代码能运行，再改写工作副本。模型只能替换已有应用 `.py` 文件，不能改测试、配置或安装依赖。完成后导出可独立运行的新项目。
2. **AI worker**：自主执行多轮改写和验证；失败结果进入下一轮提示。保存任务、代码、公开计划、已完成工作、设计决定、下一步、完整请求及已收到的响应。支持暂停、进程中断后恢复和不同 worker 接续。
3. **数据库接口**：`ContextPort.read/write`，默认 `NullContext`。数据库记忆与本地恢复检查点分开，未来可替换 SpacetimeDB 实现。

**范围**：可信的小型 Python 项目，最多 100 个上下文文件、180000 字符。当前不支持创建/删除模块、修改测试或自动安装目标项目依赖。优化质量依赖模型与目标测试；通过测试不能证明完全语义等价。mock 仅验证流程，不代表真实 AI 优化。

## 安装

Python 3.10+。Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
$py = '.\.venv\Scripts\python.exe'
```

Linux/macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

后续示例用 PowerShell 的 `& $py`；Linux/macOS 换成 `python`。如果系统 `python` 仅是 Windows Store 别名，需要先安装 Python，或使用已配置的 `.venv`。

## 先运行旧代码

```powershell
Push-Location examples/legacy_orders
& ../../.venv/Scripts/python.exe demo.py
& ../../.venv/Scripts/python.exe -m pytest -q
Pop-Location
```

演示输出包含订单 `O-1001` 和收入 `110.00`。`checks.json` 定义“运行 demo + 回归测试”两项固定验证；新旧代码使用相同命令。验证在独立临时副本里执行，不会污染基线和检查点。

## 无 API 的暂停 / 恢复演示

```powershell
& $py -m ghostgraph start --input examples/legacy_orders --run-dir runs/demo --provider mock --checks-file examples/legacy_orders/checks.json --stop-after 1
& $py -m ghostgraph status --run-dir runs/demo
& $py -m ghostgraph resume --run-dir runs/demo
& $py -m ghostgraph export --run-dir runs/demo --output outputs/modernized
& $py outputs/modernized/demo.py
```

第一轮写入演示标记后暂停，第二次进程读取保存的代码和 handoff 后完成。只有 `phase=completed` 且通过验证的项目允许导出。

## 真实 AI 独立改写

```powershell
$env:NVIDIA_API_KEY = 'your-key'
& $py -m ghostgraph start --input examples/legacy_orders --run-dir runs/ai-01 --checks-file examples/legacy_orders/checks.json --goal 'Separate pricing and order state responsibilities; remove duplication while preserving public APIs and observable behavior' --max-steps 8
& $py -m ghostgraph export --run-dir runs/ai-01 --output outputs/ai-01
```

默认沿用原项目的 NVIDIA 模型配置；实际账号是否有该模型需自行确认。也可设置 `GHOSTGRAPH_API_KEY`、`GHOSTGRAPH_BASE_URL`、`GHOSTGRAPH_MODEL` 或传 `--base-url`、`--model`。密钥只从环境读取，不写入检查点；模型、endpoint、温度、token 上限和验证命令都会记录。

新项目需要先安装其运行依赖。默认验证为当前解释器的 `-m pytest -q`。可用 `--checks-file checks.json` 指定 JSON 参数数组，例如：

```json
[["{python}", "demo.py"], ["{python}", "-m", "pytest", "-q"]]
```

不经过 shell，`{python}` 使用启动 runner 的解释器。不要把 shell 管道或重定向当参数。每条命令默认超时 90 秒，使用 `--timeout` 调整。验证会执行项目代码，只用于可信项目；这不是安全沙箱。

## 暂停、切断、恢复

- **可重复实验的暂停点**：`start/resume --stop-after 1`，完成一轮并交付事件后暂停。
- **另一终端请求暂停**：`ghostgraph pause --run-dir runs/ai-01`。当前调用结束后在下一持久化边界停下。
- **立即中断当前调用**：Ctrl+C。之后 `ghostgraph resume --run-dir runs/ai-01`。
- **进程被强杀**：同一条 resume 命令恢复；不需要手工删除锁。操作系统释放进程锁。
- **耗尽轮数**：退出码 1，保留当前代码；`resume --extra-steps 4` 追加预算。
- **API/数据库暂时不可用**：退出码 2；修复连接后 resume，保留原请求。

`resume` 不需要原始输入目录，使用 run 中的输入快照和检查点。已经落盘的完整模型响应会重用。若进程在收到并保存完整响应前被切断，该请求会重发，可能重复计费且输出不同。未输出的模型内部思考无法恢复；持久化的是明确写出的计划和决定。保证针对进程中断，不宣称断电/磁盘损坏下的数据库级持久性。

## 同一中断点的 A/B 续写实验

先从 `none` 模式产生共同检查点，避免之前数据库状态通过 handoff 污染对照组：

```powershell
& $py -m ghostgraph start --input examples/legacy_orders --run-dir runs/seed --provider mock --checks-file examples/legacy_orders/checks.json --stop-after 1
& $py -m ghostgraph fork --run-dir runs/seed --output runs/control --context-adapter none
& $py -m ghostgraph fork --run-dir runs/seed --output runs/repeat --context-adapter none
& $py -m ghostgraph resume --run-dir runs/control
& $py -m ghostgraph resume --run-dir runs/repeat
& $py -m ghostgraph compare --left runs/control --right runs/repeat
```

实现数据库适配器之后，第二个分支可换成：

```powershell
& $py -m ghostgraph fork --run-dir runs/seed --output runs/with-db --context-adapter my_adapter:create_port --memory-ref frozen-v1
& $py -m ghostgraph resume --run-dir runs/with-db
```

两组共享相同代码、目标、公开 handoff、历史和模型参数；实验组多出适配器返回的记忆。`--memory-ref` 请求冻结数据库版本，由适配器实现读取隔离；实际返回的 `state_ref` 随请求存档。不能仅指定不同 adapter 就假定数据库实验完全受控：需要适配器确保各分支写入不互相污染。

`compare` 报告共同起点、参数一致性、验证结果、设计决定和代码文本相似度；相似度不代表语义等价或内部思考相同。真实实验应使用真实 provider、多次重复，并人工或通过任务指标评价设计决定。

## 数据与接口

```text
runs/example/
  input/                         原始项目快照
  HEAD.json                      当前检查点指针
  checkpoints/<id>/state.json    当前阶段、配置、公开 handoff、历史、事件 outbox
  checkpoints/<id>/project/      对应的完整代码
  responses/<request-id>.json    完整模型响应
  run.lock                      操作系统进程锁
  work/                         临时修改和验证副本
```

不要手动改检查点；恢复时校验哈希。不自动清理检查点，便于实验审计；长实验会增加磁盘占用。`status` 中的 `phase` 是持久化进度，强杀后不一定显示 `paused=true`，也不表示 worker 仍在线。

详见 [架构与恢复协议](docs/ARCHITECTURE.md)、[数据库接口约定](docs/CONTEXT_PORT.md)。本版 CLI 使用子命令，替代旧版 `ghostgraph --input ... --output ...`。旧 0.1 输出没有恢复状态，不能直接 resume。

## 开发验证

```powershell
& $py -m pytest -q
```

测试覆盖真实文件修改、基线失败、验证失败后修复、异常响应反馈、暂停恢复、进程强杀、响应缓存、事件重试、锁、受保护文件、导出和实验分叉。示例项目的 7 个回归测试另行执行，或通过 checks.json 一并运行。
