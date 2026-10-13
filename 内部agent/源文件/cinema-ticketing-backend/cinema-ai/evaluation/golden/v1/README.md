# Cinema Golden v1

168 条保留验收问题：原 144 条 + 24 条澄清后补问；标准与口语各 84 条，9 类意图，72 个独立 `source_case_id` 场景。

## 文件

- `cases.json`：问题、上下文、可信测试用户编号、预期意图、允许工具计划、事实检查及记录关联检查。
- `observed_clarifications.json`：原评测全部 38 次澄清观察，实际涉及 19 道题、各两轮。观察不改变预期答案，重复轮次不增加问题数。
- `metadata.json`：来源、冻结日期、清单/快照校验值与所需私有绑定名称。

订单号使用 `OGOLD000001` 等占位符。真实绑定与业务快照保留在被 Git 忽略的评测输出目录；不把密钥或绑定放进本目录。

## 使用范围

冻结业务日期：2026-10-11。实测前需通过业务快照一致性检查；数据变化则建立新版本，不能沿用旧预期硬算准确率。

本集合用于最终验收，不用于训练和阈值调参。标准/口语变体、澄清与补问按同一个原场景隔离，不能分散到训练和验收两边。新回流样本先保存为 silver，人工复核后进入独立数据集，不自动污染本集合。

## 离线检查

在 `cinema-ai` 目录运行，不调用云端模型或业务工具：

```powershell
./.venv/Scripts/python.exe -m evaluation.routing_audit evaluation/golden/v1/cases.json --date 2026-10-11 --output ../target/agent-evaluation/glm-l1-20261011/golden-routing.json
```

路由匹配不等同于答案准确率。完整对比使用 `evaluation.run --baseline-mode glm-ab`，需另传私有绑定与业务快照。

完整操作指南：`docs/agent-glm-golden-feedback-ab-2026-10-11.md`（仓库根目录）。
