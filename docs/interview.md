# AI Agent / AI 应用开发面试准备

面向当前 V2 实现。个人项目，使用合成数据并包含 AI 辅助开发；不代表 ABB 内部系统、企业上线或业务收益。以下是代码与证据导读，不代表已经独立掌握；讲到个人贡献时，请如实区分自己设计、验证和借助 AI 完成的部分。

## 1. 项目介绍：1 分钟

> 这是一个面向供应链补货的 LLM + 运筹优化决策 Agent。输入可以是“先查询库存，再预算 9000 元，电机不能缺货”。DeepSeek 负责理解意图与调用工具，SQLite 提供业务事实，RAG 检索采购政策，MILP 计算补货量，再由独立 Validator 检查约束后发布方案。设计重点是让语言理解、数学求解和可行性验证各自承担明确职责，并保留完整 Trace。项目有六类业务工具，在固定合成留出集上 hybrid 的 Agent E2E 为 22/24，检索 Hit@1 为 11/12；当前完整测试为 318 项通过。Docker 已本地实测，但数据与评测规模都较小，没有生产业务效果证明。

若只剩 20 秒：讲清“自然语言约束 → 可信数据 → MILP → 独立验证”与合成数据边界即可，不必堆完所有技术名词。

## 2. 技术架构怎么解释

按一次请求走读 [README 架构图](../README.md#architecture)：

1. FastAPI 接收请求，Pydantic 验证输入，取得一致的 SQLite 业务快照。
2. Agent 判断意图，针对当前状态开放允许调用的工具；LLM 在允许范围内选择工具和参数。
3. 查询工具取得库存、供应商、订单；RAG 取得采购政策原文与引用 ID。
4. 优化请求进入 MILP，Validator 重算方案可行性；普通查询直接返回事实。
5. 模型选择证据 ID，代码渲染事实与引用，并保存运行终态与 Trace。

入口：[API](../src/supplychain_agent/v2/api.py)、[Agent](../src/supplychain_agent/v2/agent.py)、[Trace](../src/supplychain_agent/v2/trace.py)。测试：[V2 Agent/API](../tests/test_v2_agent.py)。

**常见追问：这是自主 Agent 还是固定工作流？** 是受限的工具调用 Agent：LLM 确实选择意图和工具调用，但状态机限制调用范围、先决条件与次数。既不是无限制自主代理，也不是 Multi-Agent。没有复杂任务长期记忆或跨任务恢复。

## 3. 为什么使用 LLM

LLM 的作用是将用户不同表达转化为已支持的结构化意图与条件，处理澄清/拒绝，并选择工具与解释证据。它不提供库存事实，也不负责算最优采购量。

结构化 `/optimize` 不需要 LLM，离线 `demo` 使用保守规则句式。二者分别作为确定性入口和可复现演示；不能把离线结果说成 DeepSeek 理解能力。LLM 带来表达灵活性，也增加参数抽取错误、网络依赖、时延与费用。

复习：[意图与 Tool Calling 协议](../src/supplychain_agent/v2/model.py)、[响应契约](../src/supplychain_agent/v2/contracts.py)、[语言层测试](../tests/test_language.py)。

**追问：Schema 通过就表示理解正确吗？** 不表示。Schema 检查结构与范围，语义正确性还要看是否忠实保留了用户预算、计划期、保护物料等条件。这正是固定评测要检查工具参数的原因。

## 4. 为什么结合优化算法

补货决策要同时满足多个可验证约束。LLM 直接给数字不能保证整数、预算或 MOQ；MILP 可以明确表达约束与目标，并报告求解状态。

- 变量：每个 SKU 的整数采购量 `q`、是否订购 `y`、期末库存和缺货量。
- MOQ：`MOQ * y <= q <= U * y`，`y` 为二元变量，允许完全不采购。
- 目标：采购成本 + 持有成本 + 缺货惩罚；预算仅约束采购支出。
- 交期：超出计划窗口的新采购不能用于本期方案；这是单期简化，不是逐日仿真。
- 服务约束：按 SKU 检查最低满足量，明确保护的物料要求零缺货。

当前实际 Solver 是 **SciPy / HiGHS**；不将其他研究中使用过的 Gurobi 写成这个 Agent 的求解后端。不可行时保持原约束，不擅自加预算或延长交期。

复习：[数学模型](model.md)、[求解与验证源码](../src/supplychain_agent/optimizer.py)、[优化器测试](../tests/test_optimizer.py)。需能手算一个两物料实例，并区分 optimal、feasible、infeasible、求解错误。

## 5. Agent 如何调用工具

六类工具：`inventory_query`、`supplier_query`、`order_query`、`policy_retrieval`、`replenishment_optimizer`、`solution_validator`。`finish_request` 仅为终止控制信号，不是第七类业务工具。

DeepSeek 返回原生 function tool call；程序对名称、参数、意图一致性和执行先决条件做检查，再从注册表调用确定性函数。查询使用参数化 SQL，不执行模型拼接的任意 SQL。优化必须先有库存、供应商和政策证据，成功生成 proposal 后才调用 Validator。

有界执行控制模型调用、工具尝试和修复次数。工具失败不等同于求解不可行；重试耗尽明确结束并记录。普通同步工具没有进程级强制超时，不能声称具备任务级强隔离。

复习：[工具注册表与 execute](../src/supplychain_agent/v2/tools.py)、[状态机 available_tools / ready](../src/supplychain_agent/v2/agent.py)、[工具和数据库测试](../tests/test_v2_tools_db.py)。

## 6. RAG 的作用与 hybrid 取舍

RAG 负责回答“这个决策引用了什么采购政策”，不负责预测需求，也不自动将任意文档变成 Solver 约束。

| 设计点 | 当前实现与理由 |
| --- | --- |
| 分块 | 共用 7 份合成政策、8 个片段；Markdown 分段，最多 700 字符、无 overlap，保留标题与引用 |
| Lexical baseline | TF-IDF 中文双字/英文词特征，适合直接词面匹配 |
| Embedding | BGE-small-zh-v1.5，512 维，固定 ONNX 权重；CPU、CLS pooling、L2 归一化 |
| 相似度 | FAISS `IndexFlatIP`；归一化向量的内积等价于 cosine |
| RRF | 两路各 top-5，按片段 ID 等权加和 `1/(60+rank)`，默认最终 top-3 |
| 小规模取舍 | 8 个片段使用内存精确索引；没有外部向量数据库、reranker 或训练融合模型 |

固定检索留出集 12 条：lexical Hit@1 10/12、semantic 8/12、hybrid 11/12；hybrid Hit@3 12/12，但 Recall@3 为 0.9583，因为部分问题有多份相关文档。不能说“RAG 准确率 100%”。

默认 hybrid 是检索覆盖方面的取舍，**没有提高本次 Agent E2E 成功数**：lexical 与 hybrid 都是 22/24；hybrid 还增加时延与 token 用量。不能只挑改善的数字讲。

复习：[检索实现](../src/supplychain_agent/v2/semantic_retrieval.py)、[Embedding](../src/supplychain_agent/v2/embeddings.py)、[检索测试](../tests/test_semantic_retrieval.py)、[真实模型集成](../tests/test_semantic_integration.py)、[默认策略证据](../RETRIEVAL_BACKEND_DECISION.md)。

## 7. Validator 如何保持独立

Validator 使用可信快照、锁定参数和方案明细重新计算库存、采购量、MOQ、预算、交期和服务条件，不复用 MILP 约束矩阵。V2 还检查汇总成本与满足率。校验失败或解释生成失败时，不向用户发布未经确认的采购方案。

**独立可行性验证不等于独立证明全局最优。** 最优性依赖 Solver 状态、界与 gap；Validator 关注方案是否满足建模条件，也无法证明模型本身覆盖了现实世界所有约束。

139 checks 来自特定演示方案，不能写成每次请求固定 139 项安全防护。对应[本次合成响应](assets/demo-v2.response.json)。复习 [validate_solution](../src/supplychain_agent/optimizer.py)、[solution_validator](../src/supplychain_agent/v2/tools.py)、[优化器测试](../tests/test_optimizer.py)与[工具测试](../tests/test_v2_tools_db.py)。

## 8. 遇到的问题、处理与未解决项

| 问题 | 当前处理 / 真实结论 | 证据 |
| --- | --- | --- |
| 模型输出看似合法但遗漏显式条件 | 状态机与严格参数协议能限制执行范围，但不能消除理解错误；hybrid 留出案例 `v2-test-17` 仍因参数问题失败 | [E2E 诊断](../evaluation/retrieval_backend_e2e_report.md) |
| 检索命中但最后没有正确引用 | 检索与最终证据选择分别评测；`v2-test-22` 失败保留，没有宣称已修复 | [E2E 原始索引](../evaluation/retrieval_backend_e2e_results.json) |
| semantic 不一定优于 lexical | 保留三路对照；不改留出答案，以 RRF 合并互补排序；E2E 持平如实报告 | [检索结果](../evaluation/release/retrieval/summary.json) |
| 无模型安装路径与默认 hybrid 不一致 | 本轮修正 Makefile 的安装/启动配置，给出 lexical 和 hybrid 两条路径 | [运行指南](running.md) |
| Docker 下载中断 | 最初两次失败；增加下载缓存、降低并发后构建成功，未改版本或关闭 TLS 校验 | [本轮运行复核](reproduction-check.md) |
| 展示脚本可能把失败画成成功流程 | 新脚本读取真实 Response；查询不画采购表，不可行不标验证成功，缺 Key 不回退；5 项测试覆盖边界 | [Demo 测试](../tests/test_demo_v2.py) |

面试时不要把未解决的两个 E2E 失败编成“最终全部修复”。说明如何定位、如何设计下一轮验证，比声称没有问题更可信。

## 9. 可以继续优化的方向

优先改善证据质量：独立标注更多业务请求、分开评估参数理解/检索/最终引用，并保留新的独立测试集。其次研究无相关文档的拒答阈值、参数确认交互、多期库存与不确定需求建模。这些是未来方向，当前尚未实现。

生产使用还需要身份与授权、人工审批、真实业务数据治理、容量和故障恢复验证。项目没有实现这些能力，也不以 Docker 本地运行代替生产部署。

## 面试前自测

- 不看文档画出一次查询和一次优化的不同路径。
- 运行 [Demo](demo.md)，解释每个采购数字和政策引用来自哪里。
- 在纸上写出 MOQ 的两个约束，解释缺货惩罚与预算的区别。
- 打开两个 hybrid 失败案例，区分“工具/求解正常”与“端到端评测失败”。
- 区分历史 313 项测试和本轮 318 项测试：新增 5 项仅覆盖展示封装，不代表业务准确率增加。
- 说明自己实际完成和能够独立复现的贡献。尚不能解释的部分标记 `INTERVIEW_PREPARATION_REQUIRED`，不要用背诵代替代码走读。
