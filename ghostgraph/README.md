# GhostGraph 示例项目

- `input/`：2014 风格的旧订单系统、运行场景和回归测试；作为只读重构输入。这是演示代码，并非真实公司的生产代码。
- `output/<run-id>/`：worker 完成且验证通过后自动保存的新项目。每次运行单独保存，不覆盖之前的实验。
- `output/latest.json`：最近完成结果的索引，供前端重新打开时读取。

在 input 目录运行 `../../.venv/Scripts/python.exe demo.py` 或 `../../.venv/Scripts/python.exe -m pytest -q`。

前端左侧显示原始代码；运行中右侧显示真实检查点代码，完成后读取 output 中的结果。红色表示删除/替换，绿色表示新增/替换。没有生成结果时右侧留空。Mock 仅验证流程，不是真实 AI 重构；真实模型需配置 provider 和 API key。
