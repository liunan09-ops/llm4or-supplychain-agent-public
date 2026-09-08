# V2 评测协议

数据均为 synthetic / demo data，由开发阶段 AI 辅助编写；不是企业数据或第三方盲测。

1. 保留 `evals/cases.jsonl`、`evals/cases-v1.1.jsonl` 内的 dev/test 分割和原历史报告。当前开发者已读过 V1 test，后续运行只称回归。
2. `dev_v2.jsonl` 用于调试；所有开发集真实调用尝试分别保留。最后一次开发运行结束前不再修改实现。
3. 将 `src` 全部 Python、采购规则 Markdown、环境版本和锁文件 hash 存入 `evidence/pre_heldout_freeze.json` 后，才创建 `heldout_v2.jsonl` 与独立检索留出集。检查 ID 和完整请求无交集。
4. 留出结果不用于修改规则、提示词或放宽评分。测试、Docker 和 README 阶段可新增工程文件；若必须改变推理代码，应标记留出失效并重新设计数据，不能保留“未见留出集”的说法。
5. 小样本由同一开发过程编写，存在表述/标注偏差。没有独立标注员、跨企业分布或置信区间结论。固定温度不保证模型服务完全可复现。

## 指标口径

- 系统 intent accuracy：最终锁定意图与标注一致，包含拒绝/数字防护。raw model intent accuracy：只统计实际得到模型意图响应的请求，取记录中的最后一次意图响应，单列分母。
- tool selection accuracy：每例尝试调用的业务工具集合与期望集合完全一致；结束控制工具不计入业务工具。状态机会限制可选工具，因此不是无约束工具选择 benchmark。
- tool argument accuracy：按请求统计，要求所有尝试参数合法、锁定参数语义等价，查询 SKU 正确且覆盖完整，validator 使用实际 proposal id。重试中出现过错误参数仍记错。
- retrieval hit：Agent 取回的 citation 至少包含一个标注相关文档。独立 retrieval 分别计算 Hit@1、Hit@3、文档 Recall@3 和截断 MRR@3；不调用 LLM。不能将 Hit@3 当成最终回答准确率。
- constraint pass：只对实际发布的可行方案运行独立校验，分母不含失败、查询和不可行请求；必须同时报告端到端成功率，防止少输出方案抬高约束通过率。
- end-to-end success：最终意图、参数和状态正确，完成期望工具工作，数据库查询答案一致，输出方案满足原始期望约束，政策回答含相关实际 citation。已安全恢复的错误工具尝试不单独否决端到端成功；它仍降低参数指标。
- clarification/refusal correctness：对应标注子集上意图和状态正确，且未执行工具。明确标记防护规则直接拒绝的数量，不包装成模型能力。
- 延迟为每次 Agent 请求墙钟时间，含 API、工具、trace 写入和重试，报告 p50/p95；不是生产并发压测。
- 调用数包括真实模型请求和 HTTP 尝试，token 为 API usage 返回值的合计；缺失或重试潜在费用标记 `usage_known=false`。没有版本化、含缓存价格的费率表，金额记 null。
- Tool failure 通过显式故障注入：库存工具持续返回可重试不可用，正确行为为有限重试后终止。成功处理故障也计入对应任务成功；不冒充真实数据库事故。

## 可复现命令

```bash
uv run --frozen python -m supplychain_agent.v2.evaluation --dataset evaluation/dev_v2.jsonl --mode demo --output evaluation/runs_v2/dev_demo_final.json
uv run --frozen python -m supplychain_agent.v2.evaluation --dataset evaluation/dev_v2.jsonl --mode llm --output evaluation/runs_v2/dev_llm_final.json
uv run --frozen python -m supplychain_agent.v2.evaluation --dataset evaluation/heldout_v2.jsonl --mode llm --output evaluation/runs_v2/heldout_llm.json
uv run --frozen python -m supplychain_agent.v2.evaluation --dataset evaluation/heldout_v2.jsonl --mode demo --output evaluation/runs_v2/heldout_demo.json
uv run --frozen python -m supplychain_agent.v2.evaluation --dataset evaluation/retrieval_heldout_v2.jsonl --mode retrieval --output evaluation/runs_v2/retrieval_heldout.json
```

Demo 是保守的完整句式 DSL，自由改写可能要求澄清；其留出成绩不代表 LLM。JSON 原始记录包含每条请求、已知 usage、完整工具轨迹、政策片段、源 hash 和业务 snapshot。
