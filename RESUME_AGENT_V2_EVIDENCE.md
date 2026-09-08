## 推荐项目名称

**面向供应链补货的 LLM 工具调用与优化决策 Agent**

项目说明建议标注：个人工程项目，synthetic / demo data，AI-assisted development。不是 ABB 内部系统，不包装成企业生产经历。

## 技术栈

Python、DeepSeek 原生 Tool Calling、显式状态机、FastAPI、Pydantic、SQLite、SciPy/HiGHS MILP、独立 Validator、TF-IDF、BGE 预训练 embedding、ONNX Runtime、FAISS、Cosine Similarity、Hybrid Retrieval、RRF、Pytest、uv。

Semantic Retrieval 阶段已经用真实固定权重实测；默认 API 仍为 lexical。模型、退步案例与对照口径见 [本阶段报告](SEMANTIC_RETRIEVAL_REPORT.md)。此文件更新简历素材口径，未修改简历 PDF。

Docker 已编写配置但未通过实机 build/run 验收，暂不把“容器部署”作为完成能力。没有使用 LangGraph、LangChain、Multi-Agent、Redis/Kafka 或 Kubernetes。

## 可安全写入简历的数字

| 数字 | 必须带上的口径 | 证据 |
| --- | --- | --- |
| 6 类业务工具 | 另有结束控制工具，不能混算业务工具数量 | v2/tools.py，原生调用 trace |
| 7 份文档、8 个片段、512 维 BGE | 合成采购制度，三路共用同一原始分块 | evaluation/semantic_v2/comparison/freeze.json |
| 本阶段新增 39 项、完整 308 项通过 | 原 Core 269 项全部保留；含 3 项真实模型集成测试，0 fail/error/skip | evaluation/semantic_v2/verification.json |
| Core 22/24，91.67% | 历史默认词法版本的 LLM 端到端成绩；未重跑新后端在线 LLM，不是第三方盲测 | evaluation/runs_v2/heldout_llm.json |
| lexical Hit@1 10/12、Hit@3 11/12 | 原固定独立检索留出，重跑逐例一致 | evaluation/semantic_v2/comparison/heldout_lexical.json |
| semantic Hit@1 8/12、Hit@3 12/12 | 首位命中有退步，不能只据 Hit@3 宣称全面提升 | evaluation/semantic_v2/comparison/heldout_semantic.json |
| hybrid Hit@1 11/12、Hit@3 12/12、Recall@3 0.9583 | 同一 12 条合成留出，RRF 等权融合；不是答案准确率或生产召回 | evaluation/semantic_v2/comparison/heldout_hybrid.json |

留出模型调用 97 次、API 报告 156201 tokens、p50/p95 3.626/7.276 秒可用于面试讲实验，但不建议占用简历篇幅：这是一次顺序小样本运行，不是生产性能或人民币成本。

## 推荐 3 条简历 bullet

- 基于 DeepSeek 原生工具调用与显式状态机构建 6 类业务工具，支持库存查询、政策检索、补货优化及失败处理。
- 使用 SQLite 快照与 MILP 独立校验预算、MOQ、交期；增加本地 512 维 BGE 语义检索及 TF-IDF + RRF 混合检索，保存 trace 与原文引用。
- 在同一 12 条合成检索留出问题上，hybrid Hit@1 为 11/12、Hit@3 为 12/12、Recall@3 为 0.9583；本阶段新增 39 项测试、完整 308 项通过。

以上三条适合在项目标题旁注明“AI 辅助开发 / 合成数据”。若版面有限，优先保留原始计数，避免只写百分比让样本规模消失。

## 面试可讲的系统架构

FastAPI 接收请求，SQLite 提供一致业务快照；DeepSeek 解析意图，状态机按任务开放可用工具，模型返回原生工具调用并处理反馈。优化前读全量库存、供应商和采购规则，MILP 返回 proposal id，独立 Validator 通过后才发布结果。最后模型选择证据 ID，代码组织事实与 citation，所有步骤保存到 SQLite。

查询任务不运行求解器；不可行保持原约束；模型输出缺依据时有限修复后终止。Demo 是保守 DSL，Core 真实 LLM 路径有实际 API 记录。TF-IDF baseline 不变；新增 BGE 的 CLS + L2 + FAISS cosine 检索，以及每路 top-5、常数 60、等权 RRF。模型文件固定 revision 和 SHA-256，显式准备后本机离线推理。

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
11. **语义检索一定更好吗？** 本次 semantic Hit@1 从 lexical 的 10/12 降到 8/12；hybrid 为 11/12。模型可能把审批等邻近主题排在首位，词法精确词面信号有补充价值。这是 12 条小样本观察，不是通用结论。
12. **为什么 Hit@3 为 100% 还会漏召回？** 一条问题有两份相关文档，top-3 只取回其中一份，Hit 仍为 1，Recall 只有 0.5；总体 Recall@3 因此是 0.9583。指标不能互换。

## 当前仍存在的 evidence gaps

- Docker 无运行环境，build/run 未验证；Wheel 与本机 HTTP 成功不能替代容器验收。
- 没有真实企业数据、ERP 对接、业务降本、线上订单或生产并发指标。
- 评测由同一 AI 辅助开发过程编写，小样本、非独立第三方盲测，仍存在标注和分布偏差。
- 已有预训练语义 embedding 和 RRF hybrid；没有模型微调、reranker、长任务恢复、多用户权限或独立进程硬超时。
- 新检索模式没有独立大样本、无相关文档的拒答校准或新的在线 LLM 端到端评测；不能写“语义全面优于词法”“RAG 准确率 100%”“生产级大规模检索”或把 Core 22/24 移作新后端成绩。
- 金额成本未计算；不能写精确花费或据此推导生产经济性。

完整来源见 [最终验收报告](AGENT_V2_FINAL_REPORT.md)、[评测报告](evaluation/report_v2.md) 和 [完整文件清单](FILES_CHANGED_V2.md)。
