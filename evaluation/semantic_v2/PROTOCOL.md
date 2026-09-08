# V2 Final Hardening · Semantic Retrieval 协议

本阶段从 `ad58e78bcd98b06510bbca6f8f803f96c961e21f` 开始，在原 `supplychain-agent-v2` 分支和 `a9cd` worktree 开发。

1. 保留 Core `PolicyRetriever` 源文件、所有旧测试、原政策、开发/留出数据及原评测 JSON 的字节内容。[保护清单](protected_checkpoint_files.json) 记录 92 个原文件 SHA-256。旧 Core 的全局源码冻结属于历史证据，未改写成当前源码 hash。
2. 同一固定 retrieval dev（6 条）和 heldout（12 条）供 lexical、semantic、hybrid 逐例比较。语料仍为 7 份合成文档、8 个原片段；不得修改答案、加入同义词特例或以留出结果调整参数。这是已存在的小型合成集复用，不称新盲测或第三方测评。
3. 根据中文语料和本机 CPU 选择 BGE-small-zh-v1.5；固定 ONNX revision、FP32、CLS、查询指令、top-k 和 RRF 参数。此次未尝试其他模型、融合权重或阈值。评测程序在载入数据问题/答案前生成 [freeze.json](comparison/freeze.json)，含代码、锁文件、数据、模型、政策 hash 和环境。
4. 在同一次冻结执行中，先完成 dev 三路，再完成 heldout 三路。返回结果只受 query、政策与固定模型/算法影响，答案只在独立评分函数中使用。完成时复查输入 hash；原始记录使用排他创建，不能覆盖既有实验。
5. Hit@1 / Hit@3：分别查看前 1 / 3 个检索片段是否包含至少一个标注相关文档；分母为问题数。Recall@1 / Recall@3：先取前 k 个片段，再对文档 ID 去重，计算相关文档覆盖率，最后对所有问题取平均。不能把 Hit@3 100% 当成 Recall@3 100% 或答案准确率。
6. MRR@3 沿用 Core 口径：在前 3 个片段的去重文档序列中找第一个相关文档，取倒数，未命中记 0。多片段属于同一文档时不会重复增加 Recall。评分单测覆盖这种情形。
7. Hybrid：两路各取 top-5 片段，按 citation ID 合并候选，等权累加 `1/(60 + rank)`，返回 top-3，分数相同时按 citation ID 字典序。TF-IDF 仍过滤非正分；semantic 不使用未经校准的分数阈值。保存各路 rank、原始分数与 RRF 贡献，不训练融合模型。
8. 三路按顺序运行，时延包含 query 编码与查找，不含模型加载或语料索引构建；仅作为本机小样本记录，不是吞吐或线上性能证据。
9. 使用真实本地权重运行 opt-in 集成测试，模型缺失时显式开启测试应失败；普通单测里的 encoder double 只验证算法与异常路径，不计为真实语义能力证据。
10. 完整 pytest 后，重跑 V1 rules 36 条、V2 demo 38 条，逐例与原记录比较；另重验 76 条历史 Agent 保存响应。历史重验不是新的在线 LLM 评测。所有结果与限制一起保存，不修改简历 PDF。

固定数据 SHA-256：

- dev：`ae89b72b4796005fb26df9a95abaf3f181a758cecb086b9e0e2d0a435f93f5bf`
- heldout：`2cca33900533bd313d8e126a0046787e980f97fe36fbf04e2576c1ec54f3b387`

复现命令见 [README](../../README.md)，完整结果及可用简历口径见 [Semantic 报告](../../SEMANTIC_RETRIEVAL_REPORT.md)。
