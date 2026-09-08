# Campus Recruiting Gap Audit

**NO_ADDITIONAL_PROJECT_FEATURES_REQUIRED**

项目当前足以作为 2027 校招个人实践项目投递；不存在经本轮验证发现、必须继续加项目功能才能投递的 P0。它不能保证 offer，评价仍取决于岗位匹配、本人理解与面试表现。

| 项目 / 缺口 | 分类 | 当前处理 / 建议 |
| --- | --- | --- |
| Docker clean runtime、BGE/FAISS、Solver/Validator、重启 | 已关闭的验收项 | 实际 ARM64 构建、断网离线、真实 DeepSeek 和 SQLite 持久化均通过；无需补业务模块 |
| 测试、回归、证据、公开当前快照 | 已关闭的验收项 | 313 passed、0 failed；74 条原回归评分不变；检索和72条真实响应重评分一致；只公开经审计项目快照 |
| 直接公开现有 Git 历史 | 发布范围注意事项 | 历史仍有旧机器元数据；用干净项目快照公开即可，不是要求改写本分支历史或新增功能 |
| 24/12 条合成评测、已知模型失败、无企业流量 | 已知展示边界 | 保留分母和失败；不宣称生产效果。扩大独立评测不是本次投递门槛 |
| PyTorch、Transformer、Attention、预训练与微调原理 | Interview preparation | 准备原理和小练习；本项目没有训练/微调能力，不能为关键词硬塞训练代码 |
| BGE/CLS/L2/cosine、FAISS、RRF及检索指标 | Interview preparation | 能解释实际代码、semantic 首位下降、hybrid E2E 未提高及其时延/token 代价 |
| MILP 建模与独立验证 | Interview preparation | 能手写变量/目标/约束，区分采购预算和总目标成本；跟踪一条不可行案例 |
| Agent/Tool Calling/失败边界/SQLite | Interview preparation | 亲自复现一次 keyless demo、一次 trace，讲清状态机、参数校验、有限重试和最终证据选择 |
| 简历和项目陈述 | 投递准备 | 使用证据文档的 Agent / OR 两版；按目标岗择一，保留个人/合成/AI辅助口径；不修改本轮 PDF |
| Kubernetes/Redis/Kafka/Multi-Agent/LoRA/vLLM | 不需要增加 | 当前链路没有已验证需求；不作为投递前待办，不写已完成 |

冻结后停止功能开发。没有生产部署、鉴权/高可用、企业收益证据；这些限制无需包装为新增开发计划。
