## 推荐项目名称

**面向供应链补货的 LLM 工具调用与优化决策 Agent**

项目说明建议标注：个人工程项目，synthetic / demo data，AI-assisted development。不是 ABB 内部系统，不包装成企业生产经历。

## 技术栈

Python、DeepSeek 原生 Tool Calling、显式状态机、FastAPI、Pydantic、SQLite、SciPy/HiGHS MILP、独立 Validator、TF-IDF、FAISS、Pytest、uv。

Docker 已编写配置但未通过实机 build/run 验收，暂不把“容器部署”作为完成能力。没有使用 LangGraph、LangChain、Multi-Agent、Redis/Kafka 或 Kubernetes。

## 可安全写入简历的数字

| 数字 | 必须带上的口径 | 证据 |
| --- | --- | --- |
| 6 类业务工具 | 另有结束控制工具，不能混算业务工具数量 | v2/tools.py，原生调用 trace |
| 7 份文档、8 个片段 | 合成采购制度，词法 TF-IDF + FAISS | retrieval manifest |
| 新增 37 项、共 269 项测试通过 | 原基线 232 项；0 fail/error/skip | evaluation/evidence/test_summary.json |
| 22/24，91.67% | 冻结后合成留出请求，端到端任务成功；不是第三方盲测 | evaluation/runs_v2/heldout_llm.json |
| Hit@3 11/12 | 独立检索留出，不是最终答案准确率 | evaluation/runs_v2/retrieval_heldout.json |

留出模型调用 97 次、API 报告 156201 tokens、p50/p95 3.626/7.276 秒可用于面试讲实验，但不建议占用简历篇幅：这是一次顺序小样本运行，不是生产性能或人民币成本。

## 推荐 3 条简历 bullet

- 基于 DeepSeek 原生工具调用与显式状态机构建 6 类业务工具，支持库存查询、政策检索、补货优化及失败处理。
- 使用 SQLite 快照与 FAISS 词法检索提供决策依据，调用 MILP 求解并独立校验预算、MOQ、交期，保存执行 trace 与政策引用。
- 新增 37 项测试、合计 269 项通过；24 条合成留出请求完成 22 条，独立检索 Hit@3 为 11/12。

以上三条适合在项目标题旁注明“AI 辅助开发 / 合成数据”。若版面有限，优先保留原始计数，避免只写百分比让样本规模消失。

## 面试可讲的系统架构

FastAPI 接收请求，SQLite 提供一致业务快照；DeepSeek 解析意图，状态机按任务开放可用工具，模型返回原生工具调用并处理反馈。优化前读全量库存、供应商和采购规则，MILP 返回 proposal id，独立 Validator 通过后才发布结果。最后模型选择证据 ID，代码组织事实与 citation，所有步骤保存到 SQLite。

查询任务不运行求解器；不可行保持原约束；模型输出缺依据时有限修复后终止。Demo 是保守 DSL，真实 LLM 路径有实际 API 记录。TF-IDF 是词法 embedding，适合当前小型中文规则库；不声称已实现语义检索。

## 面试可能追问的问题

1. **为什么称为有界 Tool-using Agent？** LLM 选择任务、工具顺序/批次/参数，接收工具反馈并选择最终依据；状态机限制合法动作。不要说是无限开放自主规划。
2. **为什么不用 LangGraph？** 当前短同步流程没有人工中断和跨进程 checkpoint 需求，显式状态机更容易审查；可解释未来什么时候值得迁移。
3. **为什么不是纯 LLM 算采购数量？** 数值来自 Solver；Validator 不读求解矩阵，独立重算库存平衡、整数、MOQ、预算、交期和逐 SKU 服务约束。
4. **在途如何处理？** 只加计划窗口内到货的 in_transit 数量，received 不重复计入；单期汇总不能保证每天都不缺货。
5. **服务水平的口径？** 每个 SKU 的最低满足量向上取整；总体 fill_rate 是展示指标，不能混成全局硬约束。
6. **如何避免虚构事实？** 查询来自快照，优化必须校验，最终解释只组织已提供的证据 ID；这限制自由表达，也不保证最初意图语义必然正确。
7. **工具准确率为何很高？** 可用工具被状态机掩码限制，而且样本小；应同时报告原始模型意图、参数错误和端到端成功，不能称纯模型开放工具准确率。
8. **留出集哪里失败？** 一条最终政策引用缺失导致终止；一条显式 7 天被省略为默认值，结果虽一致，冻结的严格参数评分仍判错。不能事后为提高数字改评分。
9. **怎么处理失败和无限循环？** 最大工具/模型调用数、批次上限、有限 HTTP/工具重试与修复、HTTP/solver 超时、边界耗时检查。普通同步工具没有强制进程中断。
10. **你本人掌握了哪些部分？** 如实解释 AI 辅助范围，亲自运行测试、读懂 MILP 和 validator、跟踪一条真实 trace，并能修改约束后复测；不要把生成代码等同于独立掌握。

## 当前仍存在的 evidence gaps

- Docker 无运行环境，build/run 未验证；Wheel 与本机 HTTP 成功不能替代容器验收。
- 没有真实企业数据、ERP 对接、业务降本、线上订单或生产并发指标。
- 评测由同一 AI 辅助开发过程编写，小样本、非独立第三方盲测，仍存在标注和分布偏差。
- 没有预训练语义 embedding、reranker、长任务恢复、多用户权限或独立进程硬超时。
- 金额成本未计算；不能写精确花费或据此推导生产经济性。

完整来源见 [最终验收报告](AGENT_V2_FINAL_REPORT.md)、[评测报告](evaluation/report_v2.md) 和 [完整文件清单](FILES_CHANGED_V2.md)。
