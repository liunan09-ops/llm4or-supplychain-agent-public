# Retrieval Backend 最终决策

**发布 API 默认使用 hybrid。** `AGENT_RETRIEVAL_BACKEND=lexical` 保留无模型部署；`semantic` 仍可显式选择。原 `PolicyRetriever` 与旧评测入口继续作为词法 baseline，不删除、不覆盖。模型缺失时 hybrid 明确报错，不自动切回 lexical。

## 固定独立检索结果

同一 12 条合成留出，原数据与答案 hash 不变：

| backend | Hit@1 | Hit@3 | Recall@3 |
| --- | --- | --- | --- |
| lexical | 10/12 | 11/12 | 0.8750 |
| semantic | 8/12 | 12/12 | 0.9583 |
| hybrid RRF | 11/12 | 12/12 | 0.9583 |

开发集同为 6 条，三路 Hit@1 / Hit@3 均为 6/6，Recall@3 均为 1.0。[独立检索证据](evaluation/final/retrieval/summary.json)。Pure semantic 首位命中下降，不把它表述成全面优于 lexical。

## 真实 DeepSeek E2E 对照

在 Semantic checkpoint `f85e98b078061414b95027612f00c5ebf3b3d92c` 上固定实现、模型和评分，用同一 24 条 Agent 合成留出，按请求轮换后端顺序，每个后端运行一次。

| backend | E2E | 意图正确 | 工具集合 | 工具参数 | Agent 政策命中 | p50/p95 秒 | 模型调用 | API tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lexical | 22/24 | 23/24 | 23/24 | 21/24 | 2/2 | 3.654 / 8.060 | 93 | 149061 |
| semantic | 21/24 | 24/24 | 23/24 | 22/24 | 2/2 | 3.726 / 8.343 | 96 | 170610 |
| hybrid | 22/24 | 24/24 | 24/24 | 22/24 | 2/2 | 4.089 / 9.275 | 100 | 182691 |

三路澄清均为 4/4、拒绝均为 2/2。已发布可行方案独立重验均为 5/5。实际 Validator 调用通过数 lexical 5/5、semantic 5/5、hybrid 6/6；hybrid 有一条方案通过后，最终引用生成失败，因此没有发布，不能混淆这两个分母。

原 Core 历史 lexical 22/24 继续保留；此次 lexical 和 hybrid 各自有新的 24 条真实记录，22/24 并非沿用旧数字。[全部结果](evaluation/retrieval_backend_e2e_results.json)、[逐例失败报告](evaluation/retrieval_backend_e2e_report.md)。

## 选择依据与代价

1. E2E 完全相同，不宣称 hybrid 提高 Agent 成功率。独立 retrieval 上 hybrid 首位/前三位各多命中 1 条，优先选择更好的检索覆盖。
2. Hybrid p95 比 lexical 多约 1.22 秒，p50 多约 0.43 秒；模型调用多 7 次、API token 多约 22.6%。本次属于顺序在线小样本，差异也受模型随机性、返回内容和缓存影响，不能全归因于向量查找。
3. 本机 512 维 ONNX CPU 推理、固定 95 MB 模型文件和精确 FAISS 小索引均已运行，未出现下载/推理稳定性问题。8 个片段不需要外部服务，当前交互预算可接受；没有生产内存/并发 benchmark。
4. 默认 hybrid 的代价是首次需要显式安装 semantic extra 并准备模型。Quick Start 已调整。受限网络、最小依赖或不准备模型时，可显式选择 lexical；模型不会进入 Git 或 image。
5. 默认变更仅涉及 FastAPI 配置选择，不改 Agent 提示词、业务逻辑、求解器、Validator、检索排名算法或原评分。新增默认/覆盖/缺文件测试并进行完整回归。

小样本一次对照不证明统计显著优势。Semantic 21/24 的失败、hybrid 的引用生成失败，以及三路共同的显式 7 天参数问题均保留。没有为提高成绩调答案或扩展规则。Docker 不可用是独立运行环境 blocker，不把未验证的容器能力计入本决策的本机稳定性证据。
