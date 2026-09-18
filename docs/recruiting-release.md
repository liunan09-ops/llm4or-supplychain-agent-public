# 秋招工程化收尾记录（2026-09-18）

范围：在 `supplychain-agent-v2` 当前 worktree 上完善展示和可复现性；核心算法、业务工具、固定评测数据与旧验证结果保持不变。本轮没有增加业务功能、依赖、远程部署或重写 Git 历史，也没有 push。

## 阶段提交

| 阶段 | Commit | 内容 |
| --- | --- | --- |
| 1. GitHub 展示 | `3083337` | 补充 Agent 分支流程图与明确未实现的未来工作 |
| 2. 可运行性 | `c4201d9` | 修正 Makefile 安装/运行模式、Docker 下载缓存，增加环境与复现指南 |
| 3. 轻量 Demo | `3d52328` | 真实 V2 终端展示、离线 HTML/SVG 导出、原始合成响应、5 项边界测试 |
| 4. 质量检查 | `7cd89a6` | 忽略敏感/大体积本地产物，记录 lint、测试、回归与安全审计范围 |
| 5. 面试材料 | `9112c05` | 九个面试主题、代码/测试/评测证据索引；旧 V1 指南增加范围提示 |
| 6. 收尾 | 本文所在提交 | 统一 README 当前测试口径，记录最终范围和验证结果 |

精确 SHA 可通过 `git log --oneline -- supplychain-agent` 查询；历史阶段报告保留其当时数字。

## 修改文件与目的

| 文件 | 目的 |
| --- | --- |
| `README.md` | 招聘者首屏定位、工作流程、Demo 图、运行导航及当前 318 项测试口径 |
| `Makefile` | 明确 lexical/hybrid 准备路径，执行时不隐式移除依赖，评测输出移到 `.runtime` |
| `Dockerfile` | 保留版本与 hash，缓存下载并降低受限网络下的下载并发 |
| `.gitignore`、`.dockerignore` | 排除本地数据库、模型、密钥文件、缓存与压缩包 |
| `scripts/demo_v2.py` | 直接调用现有 V2 Agent 并展示真实执行；禁止覆盖旧输出 |
| `tests/test_demo_v2.py` | 覆盖优化、查询、不可行、缺 Key 和输出冲突，防止展示层夸大成功 |
| `docs/assets/demo-v2.svg`、`docs/assets/demo-v2.response.json` | 同一次合成演示的可视化与原始响应，公开复核数据来源 |
| `docs/demo.md` | 演示命令、模式区别、输出与截图说明 |
| `docs/running.md` | 依赖、环境变量、健康检查、Make/Docker 用法与排错 |
| `docs/reproduction-check.md` | 本轮干净安装、实际 HTTP、Docker 和 live smoke 结果 |
| `docs/quality-check.md` | 规范、类型注释边界、测试、回归、敏感信息与文件大小检查 |
| `docs/interview.md` | 1 分钟介绍与九类技术面试准备，逐项关联证据 |
| `docs/interview_guide.md` | 标记旧内容部分对应 V1，避免与当前 RAG 实现混淆 |
| `docs/recruiting-release.md` | 本收尾记录 |

## 最终验证结果

- **318 passed**，0 failed / skipped，2 条既有 Starlette/httpx、anyio 弃用警告；在新建的 Python 3.12.14 虚拟环境运行。原有 313 项 + 新增 5 项展示测试。
- Ruff check / format check 通过，59 个 Python 文件；`uv pip check` 通过，锁文件未改动。
- lexical 与 hybrid 的实际 HTTP 检查通过；BGE 权重固定 hash 验证通过。
- Docker Linux ARM64 build、断网离线、BGE/FAISS/RRF、重启及 SQLite 持久化通过；真实 DeepSeek 单次请求 completed、solver optimal、validator valid。最初两次下载失败及修复过程见运行复核记录。
- V1 36 条及 V2 demo 38 条逐例评分不变；固定检索集的三路 Hit/Recall 复跑不变。未重跑完整真实 LLM 留出评测，仍引用历史 hybrid E2E **22/24**。
- Demo 截图已渲染检查。默认离线解析明确标注 `no LLM`；展示资源与原始响应一致，未把一次演示当作 benchmark。
- 项目快照 secrets/privacy 扫描通过；无超过 5 MiB 的已跟踪文件，新文件均经过显式选择提交。
- 本轮开始时已有的 **48 个未跟踪文件**内容保持不变；**232 个核心源码与 evaluation 文件**经 SHA-256 对比未变化。原有测试也未修改，仅增加 Demo 测试文件。

原始新运行产物保存在被忽略的 `.runtime/recruiting-*` 路径，没有提交环境、缓存、数据库或模型权重。两个小样本评测中的失败仍保留。

## 发布边界

项目可用于展示当前真实能力，但求职材料应保留合成数据、小样本、无企业生产流量的限制。独立 Validator 证明建模条件下的可行性，不等于覆盖现实世界全部约束。

当前项目快照安全检查通过，**旧 Git 历史仍未完成脱敏**。不要直接推送整个求职材料仓库；后续公开应使用重新审计的干净项目快照。本轮没有同步或改写既有 `public-release/`，也没有更动简历或其他项目。等待用户确认后再处理发布。
