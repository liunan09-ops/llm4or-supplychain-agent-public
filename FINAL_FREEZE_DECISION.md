# Final Freeze Decision · 2027 Campus Recruiting

**PROJECT_FROZEN_FOR_2027_CAMPUS_RECRUITING**

本决定针对个人合成数据工程项目的校招展示与投递，不是企业生产上线验收。数据为 synthetic / demo data，保留 AI-assisted development 声明，非 ABB 生产系统。

| 必答项 | 最终判断 |
| --- | --- |
| 1. 是否存在阻碍投递的 P0？ | 在已执行测试、真实对照与证据核查范围内未发现。已知 LLM 失败与 Docker blocker 必须如实披露，不阻止当前投递。 |
| 2. 最终 pytest？ | 313/313 passed；previous 308、added 5；0 failed/error/skipped，2 个既有弃用警告；4 项真实模型集成。 |
| 3. 最终真实 DeepSeek Agent 留出？ | 同一 24 条：lexical 22/24、hybrid 22/24、semantic 21/24；新的 72 条真实记录，非沿用 Core 历史分数。 |
| 4. lexical retrieval？ | 同一 12 条留出：Hit@1 10/12、Hit@3 11/12、Recall@3 0.8750。 |
| 5. semantic retrieval？ | Hit@1 8/12、Hit@3 12/12、Recall@3 0.9583；首位效果下降保留。 |
| 6. hybrid retrieval？ | Hit@1 11/12、Hit@3 12/12、Recall@3 0.9583；不能将 Hit@3 等同于答案或 Recall 100%。 |
| 7. 默认 backend？ | API 默认 hybrid；E2E 与 lexical 持平，独立检索覆盖更好，本机时延与模型准备成本可接受。保留显式 lexical 无模型运行。 |
| 8. Docker 实测了吗？ | 没有。docker --version / info 均 exit 127，本机无 Docker；只完成配置和静态检查，不称部署成功。 |
| 9. 可用技术关键词？ | DeepSeek Native Tool Calling、有界 Agent、FastAPI、Pydantic、SQLite、SciPy/HiGHS MILP、独立 Validator、BGE embedding、ONNX Runtime、FAISS、Hybrid Retrieval、RRF、Pytest。 |
| 10. 可用数字？ | 6 类业务工具、7 文档/8 片段、512 维；313/313 tests；hybrid 合成 Agent 留出 22/24；检索 11/12、12/12、12 题 macro Recall@3 0.9583；发布方案独立重验 5/5（限定该分母）。 |
| 11. 禁止词和数字？ | 生产级、ABB 落地、实际业务降本、生产准确率、RAG/Recall/E2E 100%、E2E 显著提升、Docker 部署成功、微调/自训练、reranker、Multi-Agent/K8s/Redis/Kafka、第三方盲测、保证 offer。 |
| 12. 现在应否冻结？ | 是。工程链路、检索对照、真实后端实验、测试与失败证据已具备，继续扩功能不构成当前投递前提。 |
| 13. 冻结标识 | PROJECT_FROZEN_FOR_2027_CAMPUS_RECRUITING |
| 14. nice-to-have？ | Docker 实机验证、独立标注更大样本、无相关文档拒答阈值、显式默认参数保留、硬超时、鉴权/生产资源评测。**均不影响当前如实投递。** |

## 必须一起讲清的失败与代价

本次 hybrid 22/24 的两条失败是 v2-test-17 显式 7 天参数省略、v2-test-22 最终政策引用缺失。没有为提高成绩修改固定请求、ground truth、提示词或特殊规则。原 Core 22/24 对应 v2-test-02、v2-test-17，不混用失败说明。

Hybrid 的 100 次 LLM 调用、182691 API tokens 和 p95 9.275 秒比本次 lexical 更高，不能声称节省推理成本。已发布可行方案重验 5/5 与实际 Validator 调用 6/6 是两个分母；不得只靠高校验率掩盖 E2E 失败。

默认 hybrid 需先安装 semantic extra、准备并校验固定模型文件；应用不隐式下载或回退。Docker configuration implemented but runtime verification blocked because Docker is unavailable on the current machine.

## 证据与版本

- [最终测试及证据检查](evaluation/final/verification.json)
- [真实 E2E 全量结果](evaluation/retrieval_backend_e2e_results.json)
- [最终 retrieval](evaluation/final/retrieval/summary.json)
- [默认检索决策](RETRIEVAL_BACKEND_DECISION.md)
- [Docker 实际记录](DOCKER_RUNTIME_VERIFICATION.md)
- [完整报告](AGENT_V2_FINAL_REPORT.md) / [简历与面试素材](RESUME_AGENT_V2_EVIDENCE.md)

Core：`ad58e78bcd98b06510bbca6f8f803f96c961e21f`；Semantic：`f85e98b078061414b95027612f00c5ebf3b3d92c`。当前分支为 `supplychain-agent-v2`；包含本文件的 final commit 消息为 `feat: finalize supply chain agent v2 for campus recruiting`。

不修改简历 PDF，不 merge，不继续新增产品功能。项目外文件、zip、密钥、数据库、模型缓存及构建产物不在最终提交中。
