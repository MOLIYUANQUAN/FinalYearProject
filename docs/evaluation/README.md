# Evaluation 证据目录

本目录存放各阶段可复现的运行证据，供报告对比使用。

| 文件 | 阶段 | 说明 |
|------|------|------|
| [baseline-v1-runs.json](baseline-v1-runs.json) | Baseline | Demo 1–3 的 prompt、工具轨迹、模型回复 |
| [baseline-v1-checklist.md](baseline-v1-checklist.md) | Baseline | 人工验收清单与对照说明 |

重新生成 Baseline 证据（需 API Key，且建议在接近 `baseline-v1` 的代码上跑）：

```bash
python scripts/demo_cli.py --save
```
