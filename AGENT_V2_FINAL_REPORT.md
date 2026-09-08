# Agent V2 Final Hardening / Final Freeze 报告

项目已完成当前可执行的收尾步骤，冻结用于 2027 校招展示。数据为 **synthetic / demo data**，含 **AI-assisted development**；是个人实践，不是 ABB 生产系统、不包含 ABB 内部数据。本轮未修改简历 PDF，没有创建分支或 merge。

## 1. 版本与交付

- 分支：`supplychain-agent-v2`；worktree：`a9cd/ln秋招`。
- V2 Core checkpoint：`ad58e78bcd98b06510bbca6f8f803f96c961e21f`。
- Semantic checkpoint：`f85e98b078061414b95027612f00c5ebf3b3d92c`，消息 `feat: add semantic and hybrid retrieval`，精确提交 46 个项目文件。
- 最终提交消息：`feat: finalize supply chain agent v2 for campus recruiting`。包含本报告的 Git commit 即 final commit，SHA 由提交后命令确认，不在自身内容中循环嵌入。
- 最终清单：[FILES_CHANGED_FINAL.md](FILES_CHANGED_FINAL.md)；Semantic 清单：[FILES_CHANGED_SEMANTIC.md](FILES_CHANGED_SEMANTIC.md)。

## 2. 已实现范围

FastAPI 入口，DeepSeek 原生 Tool Calling，显式有界状态机和严格参数 schema；SQLite 一致业务快照与 trace；6 类业务工具；SciPy/HiGHS 单期 MILP；独立 Validator；原 TF-IDF baseline、本地 512 维 BGE 与等权 RRF hybrid；固定数据、逐例真实评测、离线回归及哈希证据检查。

核心链路：`请求 → SQLite 快照 → 意图/澄清/拒绝 → 工具选择 → 数据与政策 → MILP proposal → Validator → 原文证据选择 → 响应/trace`。优化前必须查询数据和政策，可行方案经校验才有资格发布；模型最终证据选择失败仍会隐藏方案。

本阶段只增加对照评测、默认配置测试和工程证据，不新增业务模块、工具、训练、Multi-Agent、分布式服务或复杂前端。

## 3. Phase 1 · Semantic checkpoint

重新完整运行 pytest：308 passed、0 fail/error/skip、2 个既有弃用警告；Ruff 通过。重复 retrieval dev/heldout 三路，排名与指标逐例和先前实验一致。[checkpoint gate](evaluation/semantic_v2/checkpoint_gate.json)。源码、测试、配置、README 与固定评测文本精确提交；模型权重、数据库、缓存、zip 和项目外文件不进入提交。

## 4. Phase 2 · 新的真实 DeepSeek E2E

同一固定 24 条 Agent 合成留出，原请求、答案、评分函数不改。固定 `deepseek-v4-flash`、temperature=0、既有工具/修复上限，轮换三路执行顺序，各跑一次。没有 mock 模型调用，没有依据失败改 prompt 或标签。此前历史 Core 22/24 单独保留，新结果由 72 条实际响应支持。

| 指标 | lexical | semantic | hybrid |
| --- | --- | --- | --- |
| 请求数 | 24 | 24 | 24 |
| E2E success | 22/24 | 21/24 | 22/24 |
| 意图正确 | 23/24 | 24/24 | 24/24 |
| 原模型意图（实际调用子集） | 21/22 | 21/22 | 21/22 |
| 工具集合完全匹配 | 23/24 | 23/24 | 24/24 |
| 全部尝试参数正确 | 21/24 | 22/24 | 22/24 |
| Agent 政策相关文档命中 | 2/2 | 2/2 | 2/2 |
| 澄清正确 | 4/4 | 4/4 | 4/4 |
| 拒绝正确 | 2/2 | 2/2 | 2/2 |
| 已发布可行方案独立重验 | 5/5 | 5/5 | 5/5 |
| 实际 Validator 调用通过 | 5/5 | 5/5 | 6/6 |
| 成功返回的 solver 结果中可行数 | 5/7 | 5/7 | 6/8 |
| optimizer 工具尝试产出可行结果 | 5/9 | 5/10 | 6/10 |
| LLM calls / HTTP attempts | 93/93 | 96/96 | 100/100 |
| prompt / completion tokens | 143379 / 5682 | 164537 / 6073 | 176643 / 6048 |
| API total tokens | 149061 | 170610 | 182691 |
| p50 / p95 秒 | 3.654 / 8.060 | 3.726 / 8.343 | 4.089 / 9.275 |

可行比例的两个分母分别是成功 solver 返回（含预期 infeasible）与所有 optimizer 工具尝试（还含参数/时序检查拒绝、未进入 solver 的尝试）。不要将这些工具拒绝称为数值求解器故障。Hybrid 6 次验证中有一条随后解释失败，故只发布 5 条可行方案。

API 报告的三路 token 均完整，金额估计为 null：原客户端未保存可可靠区分缓存命中/未命中的用量与冻结费率表。时延为顺序小样本，不是生产性能。合计 289 次模型调用、502362 tokens，仅此实验有效。

失败全部保留：

- lexical：v2-test-13 意图 schema 失败 `malformed_intent`；v2-test-17 显式 7 天被省略，严格参数匹配失败。后者虽然返回预期 infeasible，仍不能算 E2E 成功。
- hybrid：v2-test-17 同类显式参数错误；v2-test-22 `answer_policy_citation_missing`，最终政策引用选择失败，未发布已通过校验的 proposal。
- semantic：v2-test-02 达到重规划上限；v2-test-11 检索取回相关文档但最终证据选择错误；v2-test-17 显式参数错误。
- 预期澄清、拒绝、库存不可用注入和正确 infeasible 独立标注，不混成失败。诊断标签可能重叠。

[实验冻结](evaluation/backend_e2e/freeze.json) · [全部响应/指标索引](evaluation/retrieval_backend_e2e_results.json) · [失败报告](evaluation/retrieval_backend_e2e_report.md)。Core 历史失败为 v2-test-02 与 v2-test-17，不与本次 hybrid 失败混用。

## 5. Phase 3 · 默认 backend

最终 **API 默认 hybrid**。E2E 与 lexical 同为 22/24，独立检索首位与前三位各多命中一条；本次增加的时延、token 和约 95 MB 模型准备成本在当前本机交互范围内可接受。CPU 推理与依赖已实测，但没有生产资源/并发结论。

保留 `AGENT_RETRIEVAL_BACKEND=lexical` 无模型部署，以及显式 semantic。默认值改变只在 API 配置选择，不改变被比较的 Agent、模型 prompt、MILP、Validator 或排名逻辑。准备模型是默认启动前提；失败明确报错，不隐式回退。[完整决策](RETRIEVAL_BACKEND_DECISION.md)。

## 6. 独立 retrieval 最终结果

| 数据 | 方法 | Hit@1 | Hit@3 | Recall@3 |
| --- | --- | --- | --- | --- |
| dev 6 条 | 三路各自 | 6/6 | 6/6 | 1.0000 |
| heldout 12 条 | lexical | 10/12 | 11/12 | 0.8750 |
| heldout 12 条 | semantic | 8/12 | 12/12 | 0.9583 |
| heldout 12 条 | hybrid | 11/12 | 12/12 | 0.9583 |

最终重跑仍逐例一致。三路共享 7 文档/8 片段、原 700 字符分块。BGE-small-zh-v1.5 固定 ONNX FP32 revision，512 维，CLS/L2/cosine；hybrid 两路各 top-5、等权 RRF 常数 60、评测 top-3。Semantic 首位命中下降与剩余漏召回完整保留。[最终检索冻结与输出](evaluation/final/retrieval/summary.json)。

## 7. Phase 4 · Docker（历史 Final checkpoint）

实际 `docker --version`、`docker info` 均 exit 127，CLI 与 Docker Desktop 常见路径均不存在。没有安装替代平台。静态检查了非 root、锁依赖、healthcheck、可选 semantic 构建参数、只读模型挂载及秘密/缓存排除。

以上为 e10ce8f 阶段历史阻塞；本轮已由实际 ARM64 runtime 验证关闭，见文末 Final Release 与 [Docker记录](DOCKER_RUNTIME_VERIFICATION.md)。

不能声称 image build、容器启动/重启、容器内 BGE 或真实 API 成功。[完整记录](DOCKER_RUNTIME_VERIFICATION.md)。本机 Python/FastAPI 测试不能替代容器验收。

## 8. Phase 5 · 最终全量回归

- Previous 308，added 5，total/passed **313**，failed/error/skipped **0**。4 项真实 embedding 集成；2 个既有弃用警告。Ruff 通过。
- 新增 2 项测试核对 E2E 分母与失败分类；3 项核对默认 hybrid、显式 lexical 和缺权重时不静默回退。没有为数量堆叠业务用例。
- 原 308 个测试 ID 保留；Core 92 个保护文件 hash 不变，含原 lexical、旧测试、固定数据和历史结果。
- V1 rules 36 条、V2 demo 38 条重跑，评分与原版一致；demo 14/14 和 17/24 不作为真实 LLM 成绩。
- 最终 retrieval 54 个逐例结果（18 问题×3 路）重跑一致；离线重算 72 条真实 Agent 响应及所有分母。真实 API 对照在默认值切换前执行，被比较的后端实现未改；没有为默认选择重复挑选更好的在线成绩。

[测试记录](evaluation/final/test_summary.json) · [JUnit](evaluation/final/pytest-final.xml) · [离线回归](evaluation/final/regression/summary.json) · [最终证据验证](evaluation/final/verification.json)。

功能范围内未发现新回归。LLM 的 schema、显式参数、证据选择和执行上限失败仍是已知限制；本报告不把 313 项测试解释成模型永不失败。

## 9. 简历与交付边界

可写：DeepSeek Native Tool Calling、有界 Agent、FastAPI/Pydantic、SQLite、MILP/独立 Validator、BGE/ONNX/FAISS、Hybrid RRF、固定数据对照、313/313 tests、合成留出 hybrid 22/24、独立检索 11/12 与 12/12、12 题 macro Recall@3 0.9583。

不可写：ABB 内部落地、生产级/生产准确率、业务降本、RAG 或召回 100%、E2E 提升、模型微调/训练、reranker、云端/生产部署、多代理/K8s/Redis/Kafka、第三方盲测或保证 offer。

[简历素材](RESUME_AGENT_V2_EVIDENCE.md) 提供三种方向的各 3 条 bullets、技术栈一行、60 秒/3 分钟介绍及 32 个追问。源码和证据在项目目录；项目外 zip、简历脚本、tmp 和简历目录不修改、不提交。模型、密钥、数据库、缓存与构建产物不进入 Git。

## 10. Freeze

**PROJECT_FROZEN_FOR_2027_CAMPUS_RECRUITING**

没有发现阻碍以个人合成数据项目如实展示和投递的 P0。独立大样本、拒答校准、生产权限/并发和独立进程硬超时作为 nice-to-have，不影响当前投递；不再继续扩功能。最终判断见 [FINAL_FREEZE_DECISION.md](FINAL_FREEZE_DECISION.md)。

## Final Release · Runtime / Public Audit

基线 e10ce8f；在同一分支/worktree完成。默认镜像缺少 semantic 依赖的问题已实际复现并最小修复，Python/uv digest固定，新增模型准备脚本复制与目录权限，无新增业务源码/依赖/测试。全新Docker模型卷下载3个固定hash文件，断网无key离线、BGE ONNX CPU、三路FAISS检索、MILP/独立Validator及stop/start持久化通过；真实DeepSeek代表请求HTTP200/completed，7次调用、约8.82秒。Docker具体证据见 [实测报告](DOCKER_RUNTIME_VERIFICATION.md)。

完整pytest仍313 passed、0 failed/error/skip，Ruff通过；74条原离线回归评分不变，6×3开发和12×3留出检索排名/指标不变；72条此前真实E2E响应重新计分一致。没有新增在线24条统计，不把冒烟请求混进旧分母。[Release gate](evaluation/release/verification.json)。

公开审计覆盖index/工作区/项目历史blob及实际image layers；29份历史证据仅清理数据路径或JUnit主机名，旧hash保留于旧checkpoint，新gate验证变换且不改答案/指标。[安全审计](PUBLIC_REPO_SAFETY_AUDIT.md)仅准许公开已审计当前项目快照；旧历史机器元数据仍保留，不直接公开整个求职仓库。

**PROJECT_FROZEN_FOR_2027_CAMPUS_RECRUITING**

**NO_ADDITIONAL_PROJECT_FEATURES_REQUIRED**

[校招缺口审计](CAMPUS_RECRUITING_GAP_AUDIT.md)将PyTorch/Transformer/Attention等归为面试准备；不继续V3、训练、分布式功能或修改简历PDF。Release提交消息：`chore: complete runtime verification and release audit`。
