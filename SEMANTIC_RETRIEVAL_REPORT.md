# Semantic Retrieval 阶段验收

> 本文件保留 Semantic checkpoint 的阶段记录（当时默认 lexical、308 tests）。最终发布 API 默认 hybrid、313 tests 和新的真实 E2E 对照见 [最终报告](AGENT_V2_FINAL_REPORT.md) 与 [检索决策](RETRIEVAL_BACKEND_DECISION.md)。

本阶段在 `supplychain-agent-v2` / `a9cd` worktree 增加真实语义检索和可选 RRF hybrid；默认 lexical 保持不变。没有创建新分支、merge、进行 Docker 阶段或修改简历 PDF。原 Core 记录与固定数据不覆盖。

## 模型与实现

| 项目 | 实际配置 |
| --- | --- |
| 模型 | [BAAI/bge-small-zh-v1.5](https://huggingface.co/BAAI/bge-small-zh-v1.5)，预训练中文 embedding；未训练/微调 |
| 实际权重 | [Xenova ONNX 导出](https://huggingface.co/Xenova/bge-small-zh-v1.5/tree/75c43b069aac4d136ba6bc1122f995fedcfd2781)，`onnx/model.onnx`，FP32 |
| Revision | `75c43b069aac4d136ba6bc1122f995fedcfd2781` |
| 模型文件 SHA-256 | `69a0b846f4f116b5e6aabf9546ea6754d02264f3211a13a1bd69b31b8040749a` |
| 下载 | 固定 HTTPS revision + 3 文件 size/SHA-256；合计 95,291,718 bytes；失败不产生可加载的半文件 |
| 本地执行 | ONNX Runtime 1.23.2，CPUExecutionProvider，FP32；tokenizers 0.22.2，batch 8，intra/inter threads 均为 1 |
| 向量 | semantic 512 维；原 lexical 529 维 |
| Pooling / similarity | CLS → L2 归一化 → FAISS IndexFlatIP，等价 cosine；不是 mean pooling |
| Query | 前缀 `为这个句子生成表示以用于检索相关文章：`；文档不加前缀 |
| Chunking | 原 Markdown `##` 分段，每段最多 700 字符，0 overlap，前置原文档标题；三路完全共用 |
| Tokenization | 最多 512 tokens，右截断；当前 8 个片段实际 74–178 tokens，全部未截断 |
| Retrieval | 默认/评测 top-k=3，API 允许 1–5；完整小索引精确扫描，citation ID 作为并列排序规则 |
| Hybrid | 两路各 top-5、等权 RRF，常数 60；无 reranker、学习融合或查询特例 |

模型文件放在被忽略的 `.runtime/models`，不纳入 Git；程序启动和推理仅加载本地文件，不下载、不静默切回 lexical。外网下载已在本机实际完成，无环境阻塞。也支持联网机器准备后复制目录，在离线机器先做 hash 验证。具体清单见 [冻结记录](evaluation/semantic_v2/comparison/freeze.json)；CPU 推理 API 与 tokenizer 的使用分别依据 [ONNX Runtime 文档](https://onnxruntime.ai/docs/api/python/api_summary.html) 和 [Tokenizers 文档](https://huggingface.co/docs/tokenizers/api/tokenizer)。

新增两个可选直接依赖：`onnxruntime==1.23.2`、`tokenizers==0.22.2`；uv.lock 锁定它们和传递依赖。既有核心依赖版本未改变。tokenizers 的传递依赖包含 Hugging Face Hub，但应用不调用其下载或远程推理接口。

## 同一数据对照

数据均为 synthetic / demo data，仍使用原 dev 6 条、heldout 12 条以及 7 文档/8 片段。这个小样本不是新增盲测、不能推断普遍收益。口径见 [协议](evaluation/semantic_v2/PROTOCOL.md)。

| 数据集 | 方法 | Hit@1 | Hit@3 | Recall@1 | Recall@3 | MRR@3 |
| --- | --- | --- | --- | --- | --- | --- |
| dev (6) | lexical | 6/6 | 6/6 | 0.9167 | 1.0000 | 1.0000 |
| dev (6) | semantic | 6/6 | 6/6 | 0.9167 | 1.0000 | 1.0000 |
| dev (6) | hybrid | 6/6 | 6/6 | 0.9167 | 1.0000 | 1.0000 |
| heldout (12) | lexical | 10/12 (83.33%) | 11/12 (91.67%) | 0.7917 | 0.8750 | 0.8750 |
| heldout (12) | semantic | 8/12 (66.67%) | 12/12 (100%) | 0.5833 | 0.9583 | 0.8194 |
| heldout (12) | hybrid | 11/12 (91.67%) | 12/12 (100%) | 0.8333 | 0.9583 | 0.9583 |

[机器可读汇总](evaluation/semantic_v2/comparison/summary.json) 保存全部指标；六份逐例输出在 [comparison](evaluation/semantic_v2/comparison)。本阶段没有通过更换模型、指令、权重、分块、标注或特殊规则修补留出成绩。

### 收益与退步

- 纯 semantic 的首位命中 **下降 2 条**（10/12 → 8/12），同时前 3 命中提升 1 条；不能说语义模型全面胜过词法。
- Hybrid 首位命中多 1 条、前 3 命中多 1 条，Recall@3 从 0.8750 到 0.9583。分别是本数据集 Hit@1 / Hit@3 / Recall@3 的 **+8.33 个百分点**，不是企业业务改善。
- `rag-test-02`：semantic 首位命中 MOQ；两路排名融合后审批和 MOQ 的 RRF 分数并列，固定 citation ID 排序仍把审批放在首位。保留这一失败，没有修改并列规则。
- `rag-test-04/07/09/12`：semantic 把邻近主题或审批文档排在首位，hybrid 从词法排名取得补充。英文问题也未获得稳定首位效果，不能声称强跨语言能力。
- `rag-test-11`：lexical 无命中；semantic/hybrid 命中 MOQ，但 top-3 仍漏掉另一份相关的紧急采购制度。这条 Recall@3 仅 0.5，故总体 Recall@3 不是 100%。

当前规模只需两个内存索引和小型 RRF，成本可控、实现可审查，因此保留 hybrid 作为可选模式。样本过小且 semantic 有退步，**不把默认 API 改成新后端**。新模式没有无相关文档的校准拒答阈值：最近邻分数不是正确性概率，需要后续独立样本检验。本阶段到此停止，不继续调参。

## 测试与回归

实际完整命令（已完成模型准备）：

```bash
RUN_EMBEDDING_INTEGRATION=1 .venv/bin/python -m pytest --junitxml=evaluation/semantic_v2/pytest-final.xml
.venv/bin/ruff check src tests scripts
.venv/bin/python scripts/verify_semantic_evidence.py
```

- 原 Core **269** 个测试 ID 全部保留，新增 **39** 个，合计 **308 passed、0 failed/error/skip**。两条 Starlette/httpx、anyio 弃用警告沿用基线。
- 其中 3 项真实本地模型集成测试：向量形状/归一化/语义排序/重复性，以及 semantic、hybrid 分别通过 FastAPI → Agent → MILP → Validator → SQLite trace、不可行场景与过期索引检查；外部 HTTP 被测试阻断。
- 单测覆盖 RRF 分值与分量、重复候选、无词法命中、并列排序、非法输入/向量、空/被篡改语料、缺失/损坏模型、CLS 与 query instruction、下载校验/中断清理和指标去重。
- V1 rules **36 条**（dev 24 + test 12）、V2 demo **38 条**（dev 14 + heldout 24）重新执行；逐例评分均与 Core 相同。V2 demo 原有留出 17/24 保留，不隐藏其 7 条失败。
- 词法 dev 6 + heldout 12 的原始检索输出和指标与 Core **逐例完全一致**；92 个保护文件 hash 不变。另重验 76 条历史保存 Agent 响应的评分，未重新调用在线 LLM。
- 没有发现原有功能/离线评测回归。纯 semantic Hit@1 的下降是真实效果退步，已单独保留；尚未建立新模式的在线 LLM 端到端成绩。

证据：[JUnit](evaluation/semantic_v2/pytest-final.xml)、[回归汇总](evaluation/semantic_v2/regression/summary.json)、[验证记录](evaluation/semantic_v2/verification.json)。原 `verify_v2_evidence.py` 的全源码 hash 只适用 Core checkpoint；本阶段用新增验证脚本核对不可变历史及新增实验，未覆盖旧冻结证据。

## 简历可用与不可用内容

可增加关键词：**预训练语义检索、BGE embedding、ONNX Runtime、CLS pooling、Cosine Similarity、FAISS、Hybrid Retrieval、RRF、固定数据对照评测、离线模型哈希校验**。

可用表述：

> 在 7 份合成采购制度上实现 512 维 BGE 语义检索及 TF-IDF + RRF 混合检索；同一 12 条固定留出问题上，hybrid Hit@1 为 11/12、Hit@3 为 12/12、Recall@3 为 0.9583；新增 39 项测试，完整 308 项通过。

这些数字仅适用于独立检索小样本。不能写“语义全面优于词法”“RAG 准确率 100%”“召回率 100%”“新模式 Agent 端到端成功率 100%”、大规模/生产级检索、企业降本、微调模型、reranker、强跨语言检索或毫秒级生产性能。Core 原 22/24 的在线 LLM 成绩属于历史默认词法版本，不能移作 semantic/hybrid 的新在线成绩。Docker、Multi-Agent、Kubernetes、Redis、Kafka、复杂前端均不属于本阶段；没有修改简历 PDF。
