# 最终简历与面试证据 · 2027 校招

个人实践项目，**synthetic / demo data；AI-assisted development**。不是 ABB 生产系统，不含 ABB 内部数据。本文件提供可选文案，不修改简历 PDF；能否采用还应以本人能讲清和复现为准。

## 一、推荐项目名称

**面向供应链补货的 LLM 工具调用与优化决策 Agent**

偏应用岗可用“供应链决策 Agent：真实工具调用与可验证优化”；偏算法岗可用“LLM + MILP 供应链补货决策系统”。

## 二、最终技术栈分层

| 分层 | 可以使用的表述 |
| --- | --- |
| A · 可直接写简历 | Python、DeepSeek Native Tool Calling、有界 Agent、FastAPI、Pydantic、SQLite、SciPy/HiGHS MILP、独立 Validator、BGE embedding、FAISS、Hybrid Retrieval / RRF、Pytest |
| B · 可面试提，不建议全堆进简历 | 显式状态机/工具掩码、TF-IDF 中文双字、ONNX Runtime CPU、CLS pooling、L2/cosine、SHA-256 冻结、uv.lock、有限重试与 trace；Docker 只能说编写了配置、实机被环境阻塞 |
| C · 禁止写成已完成能力 | 企业生产/ABB 落地、生产级、多租户、高并发、业务降本、Docker 部署成功、模型微调/训练、LoRA、CUDA/vLLM、reranker、LangGraph/LangChain、Multi-Agent、Kubernetes、Redis/Kafka、ERP 接入 |

## 三、最终可安全使用的数字

| 数字 | 必须保留的口径 | 证据 |
| --- | --- | --- |
| 6 类业务工具 | finish_request 是结束信号，不算第 7 个业务工具 | [tools.py](src/supplychain_agent/v2/tools.py) |
| 5 SKU、3 供应商、3 订单 | 合成数据规模，不是用户/业务吞吐规模 | [database.py](src/supplychain_agent/v2/database.py) |
| 7 份政策、8 个片段、512 维 BGE | 合成采购制度；固定预训练模型，无微调 | [检索冻结](evaluation/final/retrieval/freeze.json) |
| 313/313 测试通过 | Semantic 基线 308，本轮新增 5；4 项真实模型集成，0 fail/error/skip | [最终测试](evaluation/final/test_summary.json) |
| hybrid 22/24 Agent 成功 | 本次真实 DeepSeek、同一固定合成留出；包含澄清、拒绝和故障注入；不是生产准确率 | [新 E2E 结果](evaluation/retrieval_backend_e2e_results.json) |
| lexical 22/24、semantic 21/24 | 本次真实对照，不把 hybrid 包装成提升 E2E 成功率 | [E2E 报告](evaluation/retrieval_backend_e2e_report.md) |
| hybrid Hit@1 11/12、Hit@3 12/12 | 独立检索固定留出，不能当最终答案正确率 | [hybrid](evaluation/final/retrieval/heldout_hybrid.json) |
| Recall@3 0.9583 | 12 条问题上的平均文档覆盖；跨问题累计 14 个相关文档标注项（含重复文档），取回 13 项，但 13/14 的 micro recall 不等于此 macro recall | [逐例检索](evaluation/final/retrieval/heldout_hybrid.json) |
| 已发布可行方案重验 5/5 | 本次 hybrid 发布的可行方案；不能扩大到所有请求/所有条件 | [新 E2E](evaluation/retrieval_backend_e2e_results.json) |
| 实际 Validator 调用 6/6 | 包含一条随后最终引用失败、没有发布的方案；分母与 5/5 不同 | [新 E2E](evaluation/retrieval_backend_e2e_results.json) |
| V1 36/36、V2 demo 14/14 和 17/24 | V1 评分与旧版一致；demo 留出失败保留，不能称为 LLM 成绩 | [回归](evaluation/final/regression/summary.json) |

Hybrid 本次 100 次逻辑模型调用、100 次 HTTP 尝试、182691 API tokens，p50/p95 4.089/9.275 秒可以用于面试解释取舍，不建议挤进简历；不代表 SLA 或成本。可靠人民币金额未计算。Docker 未验证，没有可写成成功的部署数字。

## 四、最终通用版 3 条中文 bullet

- 基于 DeepSeek 原生工具调用与显式状态机构建供应链 Agent，接入 6 类业务工具及 SQLite 快照，支持查询、澄清、优化与失败追踪。
- 将真实 LLM 与 MILP、独立 Validator 串联校验预算/MOQ/交期；hybrid 后端在 24 条固定合成留出请求中完成 22 条，已发布可行方案重验 5/5。
- 实现 512 维 BGE + TF-IDF/RRF 检索，12 条合成检索留出 Hit@1 11/12、Hit@3 12/12；保留全部失败证据，完整 313 项测试通过。

每条按一页中文简历约两行设计，实际行数随字体和版面变化；项目标题旁注明“个人实践 / 合成数据 / AI 辅助开发”。

## 五、偏“大模型应用 / Agent 研发”版

- 设计 DeepSeek Native Tool Calling Agent，以 Pydantic Schema 和状态机限制工具参数/顺序，实现 6 类业务工具、有限修复和 SQLite trace。
- 打通真实模型、MILP 求解和独立验证，检索与最终证据选择分开审计；hybrid 后端在同一 24 条合成留出请求中完成 22 条。
- 集成本地 BGE/FAISS 与 RRF 混合检索，独立检索 Hit@1 11/12、Hit@3 12/12；以 FastAPI 和 313 项通过测试支撑复现。

## 六、偏“OR + AI 决策智能”版

- 建立含库存、在途、MOQ、预算、交期及逐 SKU 服务约束的单期补货 MILP，通过 SQLite 同请求快照提供一致业务输入。
- 用 DeepSeek 解析需求并调用查询/优化工具，独立 Validator 重算约束和汇总成本；24 条合成留出请求完成 22 条，发布方案重验 5/5。
- 增加 BGE + TF-IDF/RRF 政策证据检索，固定 12 条检索问题 Hit@3 12/12、Recall@3 0.9583；完成 313 项测试及原离线回归。

## 七、技术栈一行版本

**Python / DeepSeek Tool Calling / FastAPI / SQLite / SciPy-HiGHS MILP / BGE-FAISS-RRF / Pytest**

## 八、60 秒项目介绍

我做了一个面向供应链补货的 LLM 决策 Agent，数据是合成的，开发中使用了 AI 辅助。重点是把语言理解、业务事实和数值决策分开：DeepSeek 选择工具，SQLite 提供库存与供应商信息，MILP 计算采购量，独立 Validator 通过后才发布方案。政策依据用 BGE 和 TF-IDF 的 RRF 混合检索，并保存原文引用和全过程 trace。最终在同一 24 条合成请求上，hybrid 完成 22 条，独立检索 Hit@3 是 12/12，完整 313 项测试通过。我也保留了失败：显式默认参数可能被模型省略，检索命中也不保证最终引用选择正确；这些数字不代表生产准确率。

## 九、3 分钟项目介绍

这个项目想回答的问题是：当用户用自然语言提出预算、保护物料和计划周期时，怎样生成一份可以检查、可以追溯的补货建议。我选了一个小型合成场景，包含 5 个 SKU、3 家供应商和在途订单，并明确它不是 ABB 内部系统。

架构上，FastAPI 接收请求，SQLite 在同一请求中提供一致快照。DeepSeek 先解析意图，再根据工具反馈选择下一步。状态机限定当前允许的工具：查询任务不跑求解器，优化必须先读全量库存和供应商、取得政策依据，然后调用 optimizer 和 validator。参数由严格 schema 检查，工具或模型失败只进行有限修复，不会静默改成 demo 或放宽预算。

优化部分是单期 MILP，包含整数采购、期末库存、缺货和订购二元变量。目标考虑采购、持有和缺货惩罚；约束覆盖库存平衡、MOQ、预算、供货上限、交期和逐 SKU 服务水平。Validator 不读求解矩阵，而是重新用业务数据检查采购量和汇总成本。可行方案即使求解成功，如果后续验证或最终解释失败，也不会发布未经确认的结果。

检索部分先保留原 TF-IDF baseline，再增加固定 BGE-small-zh-v1.5 的 512 维 ONNX 本地推理，用 CLS、L2 和 FAISS cosine 排序。Hybrid 把两路 top-5 按等权 RRF 融合。所有方法共用原分块和同一评测集，没有针对留出集写特殊规则。结果不是单向提升：纯 semantic 的 Hit@1 是 8/12，低于 lexical 的 10/12；hybrid 为 11/12。

最终真实 DeepSeek 对照中，lexical 和 hybrid 都是 22/24，semantic 是 21/24。Hybrid 的独立检索覆盖更好，但 p95 和 token 用量更高，因此我把它设为准备好模型后的默认后端，同时保留显式 lexical 模式。两条 hybrid 失败分别是显式 7 天参数被省略、最终政策引用缺失。完整测试有 313 项通过，原回归记录和全部失败都保留。当前最大限制是合成小样本、没有生产部署和独立评测；Docker 也因本机无运行环境而没有宣称验证成功。

## 十、面试追问及回答要点

1. **为什么叫 Agent？** 真实 LLM 决定意图、在允许集合中选工具、读取工具反馈并选择最终证据；不是只把自然语言转一次参数。自主范围明确有界。
2. **为什么不是普通 workflow？** 它确实有确定性工作流骨架；动态部分是模型的工具选择/顺序/批次和证据选择。不要声称无限开放规划。
3. **为什么不用 LLM 直接生成采购量？** 语言模型不保证整数、MOQ 和预算可行性。由 MILP 求解，独立 Validator 重算，LLM 处理语言交互。
4. **Tool Calling 怎么设计？** 6 类业务工具，各自 Pydantic Schema；原生 function tool 协议。finish_request 只是结束信号，参数和可用工具均由代码检查。
5. **Agent state 如何管理？** 显式 Python 状态机、已查询 SKU 集合、proposal id、verified 状态和调用预算；SQLite 保存请求、快照、事件与终态，不宣称跨进程恢复。
6. **为什么需要 clarification？** 缺少数值、冲突或不支持的条件不应被模型擅自补齐。澄清后提交完整请求；previous_request_id 只关联上下文记录。
7. **为什么需要独立 Validator？** 防止模型参数、solver 输出或汇总成本错误流入响应。它不复用求解矩阵，而从业务约束和订单数量独立重算。
8. **MILP 如何建模？** 整数采购 q、期末库存 h、缺货 s、订购二元 y；库存平衡，MOQ·y≤q≤cap·y，预算等线性约束，目标采购+持有+缺货惩罚。细节以实际 optimizer 代码为准。
9. **infeasible 怎么处理？** 保持原约束，给出阻碍说明，不自动降服务水平或放宽预算。预期不可行可算正确终态，但显式参数若抽取错误仍不算 E2E 成功。
10. **在途和交期怎么处理？** 只计窗口内且状态为 in_transit 的已有到货；received 不重复计入，cancelled 不计入。新采购交期超过窗口时不能用于本期满足需求。
11. **预算和目标成本有什么差别？** 预算限制采购支出；目标还包括持有成本和缺货惩罚。不能把总目标值当采购预算。
12. **服务水平怎么定义？** 每个 SKU 分别满足最小需求比例并向上取整；总体 fill_rate 只是展示。critical 标签不会自动成为零缺货约束。
13. **Lexical retrieval 原理？** 中文双字+英文词计数，log TF 与平滑 IDF，L2 归一化后用 FAISS 内积排序；本语料维度 529，过滤非正分。
14. **Embedding 原理？** 预训练编码器将文本映射为密集向量，以方向接近表达相关性。这里只使用公开模型推理，没有自行训练模型，也不把 cosine 当准确概率。
15. **为什么选 BGE-small-zh-v1.5？** 语料以中文为主且只有 8 个片段，小模型适合 CPU。权重和 tokenizer 固定版本/哈希，约 95 MB，离线可复现；不是声称它是所有场景最佳模型。
16. **CLS pooling 是什么？** 使用最后一层第一个 CLS token 的向量作为句向量，按模型用法 L2 归一化；不是平均所有 token。测试单独验证了池化位置。
17. **Cosine 和 FAISS 怎么配合？** 两边 L2 归一化后内积等于 cosine；IndexFlatIP 对小语料做精确扫描，不是 ANN 索引或分布式向量数据库。
18. **Hit@1、Hit@3、Recall@3 有什么区别？** Hit 只要求至少一份相关文档；Recall 看相关文档覆盖比例。先取 k 个片段再去重文档，最后按问题平均；12/12 Hit@3 不等于 Recall 100%。
19. **为什么 semantic Hit@1 更低？** 实际把审批等邻近主题排在首位，英文问题也不稳定。小型合成语料与专业词面使 lexical 有优势；保留 8/12 的下降，没有为测试改模型或规则。
20. **RRF 是什么？** 对两路各 top-5 的片段，以 citation ID 合并，累加 1/(60+rank)，等权融合；它融合排名，不直接混合尺度不同的原始分数。
21. **Hybrid 为什么更好/不一定更好？** 这 12 条检索问题上两路信息互补，Hit@1 为 11/12；但真实 Agent E2E 与 lexical 都是 22/24，且时延与 token 更多。不能做普遍因果推断。
22. **为什么不加 reranker？** 当前只有 8 个片段，已有检索对照足以支持本轮取舍。缺乏独立更大样本时继续叠模型易变成针对测试调参，冻结时不扩功能。
23. **为什么不用 Multi-Agent？** 这里是短同步请求和有限工具，单 Agent 状态机足够；多代理会增加调用、状态与评测复杂度，没有已验证业务收益。
24. **为什么不用 Kubernetes？** 当前是本机单服务与 SQLite，未验证生产并发，也没有编排需求。Docker 尚未实机通过，更不能跳到 K8s 关键词。
25. **如何评测 Agent？** 同一固定请求及 ground truth，评分与提示词隔离；分别看意图、工具集合/参数、检索、终态、约束和 E2E，保存每条失败与分母。拒绝、澄清和故障注入单独解释。
26. **22/24 两个失败是什么？** Core 历史为 v2-test-02 最终政策引用缺失、v2-test-17 显式 7 天省略；本次默认 hybrid 为 v2-test-22 引用缺失、v2-test-17 同类参数问题。相同总分不意味着同一失败，完整 trace 可查。
27. **如何控制 hallucination？** 事实来自只读快照，方案来自 solver+validator，最后 LLM 选择证据 ID、代码渲染原文；限制虚构空间，但不保证语义抽取或证据选择永远正确。
28. **如何限制无限循环和失败扩散？** 模型/工具调用上限、有限重试与重规划、工具掩码、HTTP/solver 超时和请求边界耗时检查；不宣称可以强杀任意同步阻塞函数。
29. **Docker 怎么做？** 写了锁依赖、非 root、持久目录、healthcheck、可选 semantic 构建和只读模型挂载；本机 docker 命令 exit 127，未实测 build/run，所以只能讲设计和 blocker。
30. **为什么 Validator 6/6，发布方案却只有 5/5？** Hybrid 有一个 proposal 验证成功后在解释阶段失败，没有发布。调用通过率与已发布可行方案重验不是同一分母。
31. **当前最大限制是什么？** 合成小样本、同一 AI 辅助编写过程、无独立企业分布；没有无相关文档的拒答校准、生产鉴权和并发验证。当前可用于校招展示，不能包装成生产系统。
32. **AI 辅助开发的边界？** 如实说使用了 AI 辅助设计、实现和文档；本人应能运行测试、跟一条 trace、解释 MILP/Validator 和改一个约束。不要把生成代码等同于独立掌握，也不要写“精通”。

更多证据：[最终报告](AGENT_V2_FINAL_REPORT.md)、[冻结决策](FINAL_FREEZE_DECISION.md)、[检索决策](RETRIEVAL_BACKEND_DECISION.md)、[Docker 记录](DOCKER_RUNTIME_VERIFICATION.md)。
