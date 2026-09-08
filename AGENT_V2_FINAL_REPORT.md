# Agent V2 最终验收报告

验收日期：2026-09-08。项目数据全部为 **synthetic / demo data**；开发和评测集编写包含 **AI-assisted development**。不是 ABB 内部系统，没有企业生产部署或真实业务降本证据。本次没有修改简历 PDF。

核心流程、真实模型评测、测试与本机服务验收已完成；Docker 实机 build/run 尚未验证。以下数字均来自实际执行记录。

## A. 实现内容

| 需求 | 实现与证据 |
| --- | --- |
| 先审计后修改 | [AGENT_V2_AUDIT.md](AGENT_V2_AUDIT.md)；修改前实际运行 232 项测试 |
| 复用 V1 | 原 language、schemas、optimizer、validator 和所有原测试、原评测数据/报告保留；[hash 检查](evaluation/evidence/integrity.json) |
| 数据层 | SQLite inventory、suppliers、sku_supplier、purchase_orders、policy_documents；幂等合成 seed、参数化查询、同请求一致快照、错误处理 |
| Tool abstraction | 六个业务工具、严格参数 schema、执行先决条件、proposal id、独立校验后发布 |
| Agent | DeepSeek 原生工具调用、显式状态机、可选工具掩码、最多四个工具的顺序批次、工具反馈、有限重规划与格式修复 |
| 分支 | 正常优化、查询后优化、库存/供应商/订单查询、规则查询、澄清、拒绝、不可行、工具/模型/校验失败、执行超限 |
| RAG | 七份采购制度、八个片段；TF-IDF embedding → FAISS IndexFlatIP → 原文 citation、源及语料 hash |
| 引用解释 | LLM 选择、排序已验证证据 ID，代码渲染事实与原文；检索结果与最终选择分开保存 |
| API | 保留 V1，新增 /v2/agent、/optimize、/v2/runs、/v2/health；响应 schema、request_id、错误处理 |
| Trace | 保存请求、快照、意图、可选工具、模型调用及 usage、工具参数/结果、solver/validator 状态、延迟、终态 |
| 离线审查 | scripts/replay_v2.py 重验已保存快照及方案，不调用当前业务库或 LLM；实际 HTTP smoke 中通过 |
| Evaluation | 新开发/留出请求和独立 retrieval 数据，原始逐例 JSON、聚合报告、源码冻结及隔离检查 |
| 工程化 | 更新 Dockerfile、.dockerignore、.env.example、uv.lock、Makefile；非 root、readiness、无 key demo；Wheel 打包通过 |
| README | 背景、模型定义、Mermaid、工具/状态/RAG、接口示例、trace、命令、指标口径与限制 |

## B. 未完成内容

1. **Docker build/run 未通过环境验收**：主机没有 Docker、Podman 或 Colima。两条实际命令均 exit 127，未构建或启动镜像；不能写“完成容器部署”。基础 Python 镜像也尚未锁 digest。
2. 预训练语义 embedding 和 reranking 未实现。当前是可复现的词法向量检索，不将其包装成语义大模型能力。
3. 留出集有两条未通过：最终政策引用缺失导致终止；显式 7 天被当作默认值省略导致严格参数匹配失败。没有利用这两条留出答案改提示词、规则或评分。
4. 金额成本没有估算：保存了 API usage，但没有完整、版本化且含缓存价格的费率依据，金额记 null。
5. 同步工具时限是执行边界检查，不是独立进程的硬中断；没有长任务持久 checkpoint、多租户鉴权或生产并发压测。
6. 数据全部合成，缺少第三方独立标注与企业分布评测；没有 ERP 接入或实际业务收益验证。

LangGraph 经评估后未引入，属于主动选型取舍；本项目没有宣称使用该框架。当前没有 Multi-Agent、Kubernetes、模型训练或复杂前端需求。

## C. 最终架构

`FastAPI → 同请求 SQLite 快照 → 意图识别/防护 → 状态机开放可用工具 → LLM 原生 Tool Calls → 数据/政策工具 → MILP proposal → 独立 Validator → 引用式解释 → SQLite trace`

查询任务直接进入对应数据或政策工具，不调用求解器。可行方案必须通过独立校验；不可行不自动放宽用户条件。结构化 `/optimize` 与无 key demo 经过同样的业务工具和校验，不产生 LLM 调用。

主要模块为 [v2/agent.py](src/supplychain_agent/v2/agent.py)、[model.py](src/supplychain_agent/v2/model.py)、[tools.py](src/supplychain_agent/v2/tools.py)、[database.py](src/supplychain_agent/v2/database.py)、[retrieval.py](src/supplychain_agent/v2/retrieval.py)、[trace.py](src/supplychain_agent/v2/trace.py)。完整 Mermaid 见 [README](README.md#架构)。

状态机限制最多 10 次业务工具尝试、12 次模型调用、2 次总重规划/格式修复；每次 HTTP 和可重试工具各最多重试 1 次。Tool Calling 的选择空间受状态约束，不能把工具集合指标解读为完全开放路由能力。模型最终说明为证据组织，不是自由文本推理验证。

## D. Test Evidence

实际最终命令：

```bash
.venv/bin/python -m pytest --junitxml=evaluation/evidence/pytest-final.xml
.venv/bin/ruff check src tests scripts
```

结果：**269 passed，0 failed，0 errors，0 skipped；Ruff 全部通过。** 原测试 232 项，新增 37 项。保留 Starlette/httpx 和 anyio 的两条弃用警告。控制台 pytest 显示 2.18 秒；JUnit testsuite 计时 2.166 秒，二者计时范围略有差别。

| 阶段 | 实际通过数量 | 证据 |
| --- | --- | --- |
| 原基线 | 232 | evaluation/evidence/pytest-baseline.xml |
| Phase 1 数据与工具 | 243 | pytest-phase1.xml |
| Phase 2 RAG | 247 | pytest-phase2.xml |
| Phase 3 Agent/API | 257 | pytest-phase3.xml |
| Phase 4 Evaluation | 260 | pytest-phase4.xml |
| Phase 5 故障与边界测试 | 269 | pytest-phase5.xml |
| Phase 6 工程化 | 269 | pytest-phase6.xml |
| Phase 7 README | 269 | pytest-phase7.xml |
| Phase 8 完整回归 | 269 | pytest-final.xml |

除首行完整路径外，表中 XML 均在 `evaluation/evidence/`。机器可读汇总：[test_summary.json](evaluation/evidence/test_summary.json)。新增覆盖 DB/每个工具、RAG、路由/状态、澄清、拒绝、不可行、validator 拦截、真实 HTTP MockTransport、批次执行、坏 JSON/参数、重规划、认证/网络失败、重试/超时、调用上限、API 和审计不可用。

原 V1 数据回归命令：

```bash
.venv/bin/supplychain evaluate --mode rules --split dev --output-dir reports/v2-regression-rules-dev
.venv/bin/supplychain evaluate --mode rules --split test --output-dir reports/v2-regression-rules-test
```

严格意图匹配 dev 24/24、test 12/12，记录见对应目录。V1 test 已在审计时阅读过，此次只称回归；没有把它重复作为新的盲测。

## E. Evaluation Evidence

实际真实模型命令与独立检索命令：

```bash
.venv/bin/python -m supplychain_agent.v2.evaluation --dataset evaluation/dev_v2.jsonl --mode llm --output evaluation/runs_v2/dev_llm_final.json
.venv/bin/python -m supplychain_agent.v2.evaluation --dataset evaluation/heldout_v2.jsonl --mode llm --output evaluation/runs_v2/heldout_llm.json
.venv/bin/python -m supplychain_agent.v2.evaluation --dataset evaluation/retrieval_heldout_v2.jsonl --mode retrieval --output evaluation/runs_v2/retrieval_heldout.json
```

| 指标 | 开发集 | 留出集 |
| --- | --- | --- |
| 系统意图（含防护） | 14/14 | 24/24 |
| 模型意图（实际调用子集） | 12/13 | 21/22 |
| 工具集合完全匹配 | 14/14 | 24/24 |
| 全部尝试参数正确 | 13/14 | 22/24 |
| Agent 政策相关文档命中 | 2/2 | 2/2 |
| 已发布可行方案约束校验 | 3/3 | 5/5 |
| 端到端任务成功 | 14/14 | **22/24（91.67%）** |
| 澄清正确 | 3/3 | 4/4 |
| 拒绝正确 | 1/1 | 2/2 |
| LLM 调用 / HTTP 尝试 | 52 / 52 | 97 / 97 |
| API 返回 tokens | 80340 | 156201 |
| p50 / p95 请求延迟 | 4.394 / 11.193 秒 | 3.626 / 7.276 秒 |

独立 retrieval 留出 12 条：Hit@1 10/12，Hit@3 11/12，文档 Recall@3 0.875，MRR@3 0.875。Demo 开发集 14/14，Demo 在同一自由表达留出集上 17/24，后者反映保守 DSL 的覆盖范围，不能冒充模型成绩。

源码冻结 hash 为 `a0f91e8c3b0a80bd967bf57c66f9c7236ba434b7deb68c08eccf49fb0639c40a`。创建 V2 留出集后推理源码未改变，留出运行中亦未改变。源码、数据集、规则 hash、逐例 response/trace 和所有分母见 [results_v2.json](evaluation/results_v2.json)、[report_v2.md](evaluation/report_v2.md)、[PROTOCOL_V2.md](evaluation/PROTOCOL_V2.md)。首轮失败和中间开发记录也保留，不与最终冻结指标混算。

这是一组由同一 AI 辅助开发过程编写的小型合成留出样本，不是第三方盲测。工具掩码、防护、有限修复和故障注入均属于系统的一部分。不能从样本推导生产准确率、稳定 SLA 或招聘结果。

## F. Docker / Engineering Evidence

- `docker build -t supplychain-agent:v2 .`：exit 127，`command not found: docker`。
- `docker run --rm -d --name supplychain-v2-acceptance -p 127.0.0.1:8765:8765 supplychain-agent:v2`：exit 127，同上。
- `.venv/bin/python scripts/smoke_v2.py`：在允许绑定本机端口的环境中成功，真实启动 Uvicorn、调用 V1/V2/结构化接口、检验 request_id/trace、离线重验，最后停止服务。运行时移除了 API key。
- `uv build --wheel --out-dir /private/tmp/supplychain-v2-dist --offline --cache-dir /private/tmp/supplychain-v2-uv`：实际构建成功，确认 Wheel 包含七份政策 Markdown。

机器记录：[docker.json](evaluation/evidence/docker.json)、[http_smoke.json](evaluation/evidence/http_smoke.json)、[wheel.json](evaluation/evidence/wheel.json)。Docker 配置使用锁文件和非 root 用户，但没有用配置存在替代容器成功证据。

## G. Resume-safe Evidence

| Candidate resume claim | Evidence | Safe to use? |
| --- | --- | --- |
| 基于 DeepSeek 原生 Tool Calling 和显式状态机实现六类业务工具 | v2/model.py、tools.py、真实留出 trace | 是；需说明受状态约束 |
| SQLite 同请求业务快照、已有订单在途聚合 | database.py、DB/工具测试、HTTP snapshot | 是；合成数据 |
| 七份采购制度、八个片段的 TF-IDF + FAISS 词法 RAG 与 citation | packaged policies、retrieval manifest、独立检索记录 | 是；不能写语义模型 |
| MILP 产生方案，独立校验预算、MOQ、交期、供货上限和服务水平 | 原 optimizer.py、v2/tools.py、测试与 trace | 是；单期模型 |
| 新增 37 项测试，最终 269 项全部通过 | 原/最终 JUnit + test_summary.json | 是；不能说新增 269 项 |
| 24 条合成留出请求完成 22 条，端到端 91.67% | heldout_llm.json、冻结记录、评分协议 | 是；必须带样本与合成限定 |
| 独立检索留出 Hit@3 11/12 | retrieval_heldout.json | 是；不能当成答案准确率 |
| 无密钥本机 HTTP API 与离线方案重验通过 | http_smoke.json | 是；不是容器验收 |
| Docker 生产部署成功、真实业务降本、多语言语义检索 | 无对应验证 | **否** |

## H. 禁止写进简历的内容

- “ABB 内部项目/企业真实生产数据”“节省采购成本 X%”“支撑真实用户/订单规模”。
- “独立手写全部代码”“精通 LangGraph”“使用 Multi-Agent/K8s/Redis/Kafka”，或尚未实现的模型训练、语义 embedding、reranker。
- “新增 269 项测试”“LLM 100% 准确”“所有场景约束通过率 100%”“第三方盲测 91.67%”。
- “Docker 已部署上线”“生产 SLA p95 7.3 秒”“精确人民币模型成本”“保证拿到好 offer”。
- “自由文本解释已经过完整事实验证”“总需求服务率硬约束”“逐日库存安全”“多供应商分配”“跨进程故障恢复”。

## I. 文件修改与交付索引

原文件修改：`src/supplychain_agent/api.py`、`pyproject.toml`、`uv.lock`、`Dockerfile`、`.dockerignore`、`.env.example`、`Makefile`、`README.md`。

新增核心：`v2/{contracts,database,tools,retrieval,model,agent,trace,api,evaluation}.py`、包初始化文件及 `v2/policies/*.md`；新增测试 `test_v2_tools_db.py`、`test_v2_retrieval.py`、`test_v2_agent.py`、`test_v2_evaluation.py`。

新增工程脚本：`scripts/replay_v2.py`、`scripts/smoke_v2.py`、`scripts/report_v2.py`、`scripts/verify_v2_evidence.py`。新增 V2 数据、原始运行 JSON、协议、报告、JUnit、源码冻结/完整性/部署记录位于 `evaluation/`。V1 新回归报告位于 `reports/v2-regression-rules-*`，原历史文件保持原 hash。

最终离线证据验收命令 `.venv/bin/python scripts/verify_v2_evidence.py` 已通过：确认原测试 ID 保留、冻结源码一致、保存的 Agent 结果可按原评分重算、文档本地链接有效，交付文本未检出当前配置的 API key。记录见 [final_gate.json](evaluation/evidence/final_gate.json)；这不是额外的 LLM 评测或 Pytest 数量。

文档交付：[审计](AGENT_V2_AUDIT.md)、[README](README.md)、[评测](evaluation/report_v2.md)、[简历素材](RESUME_AGENT_V2_EVIDENCE.md)、本报告。完整文件清单见 [FILES_CHANGED_V2.md](FILES_CHANGED_V2.md)。
