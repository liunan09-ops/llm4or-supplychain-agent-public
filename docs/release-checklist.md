# Supply Chain Decision Agent — 发布前检查清单

审计日期：2026-09-18。基线分支 `supplychain-agent-v2`，基线 HEAD `0396f2d94f070a3bc3ccf21a19670f4b8db9c1ac`。本文件与审计报告属于随后新增的文档提交；不改写历史，不 push。

**工程展示与运行检查通过，但当前分支不能直接作为公开 release 推送。** 需先选择干净快照发布路径、确认公开作者身份和项目许可证。完整风险、文件和 commit 定位见 [历史审计报告](git-history-audit.md)及[机器明细](git-history-audit.json)。

## 项目介绍

面向供应链补货的 LLM + OR 决策 Agent：DeepSeek 理解自然语言并调用工具，SQLite 提供业务事实，RAG 检索采购政策，MILP 计算补货量，独立 Validator 校验后输出建议与可追溯依据。

个人项目，使用 synthetic/demo data，包含 AI 辅助开发；不是 ABB 内部系统，不含 ABB 机密数据，没有企业生产流量或真实业务 ROI 证明。

## 已有功能列表

- 六类业务工具：库存、供应商、订单、政策检索、补货优化、方案验证。
- 受限 Agent 路由与原生 Tool Calling；支持查询、查询后优化、澄清、拒绝和失败终止。
- lexical baseline、BGE-small-zh-v1.5 512 维语义检索、FAISS、RRF hybrid；API 默认 hybrid。
- 单期整数补货 MILP，使用 SciPy/HiGHS；支持 MOQ、预算、交期、供货上限及逐 SKU 服务条件。
- 独立 Validator 重验方案；失败时不发布未经确认的采购建议。
- FastAPI、Pydantic、SQLite Trace、离线规则模式与真实 DeepSeek 模式。
- Docker 本地运行、模型卷只读、SQLite 持久化；V2 终端 Demo 导出 HTML/SVG 和真实 JSON。

不包含自动下单、ERP 接入、多租户鉴权、模型训练或生产部署。

## 运行方式

所有命令从项目根目录执行。依赖由 `pyproject.toml` + `uv.lock` 固定；推荐 Python 3.12 与 uv。首次安装依赖和准备模型需要联网，之后离线演示不需要 API Key。

### 最小本地 Demo

```bash
make install-lexical
make demo-v2
make serve-lexical
```

`demo-v2` 默认 `demo + lexical`，明确标注离线规则解析，不冒充 LLM。服务运行后访问 `http://127.0.0.1:8765/docs`。

### 完整 hybrid 与测试

停止之前启动的服务，再执行：

```bash
make install
make prepare-model
make test
.venv/bin/python scripts/demo_v2.py --backend hybrid
make serve
```

### Docker

```bash
docker build -t supplychain-agent:v2 .
docker run --rm -v supplychain-bge:/models/bge --entrypoint python \
  supplychain-agent:v2 scripts/prepare_embeddings.py --model-dir /models/bge
docker run -d --name supplychain-agent-v2 -p 127.0.0.1:8765:8765 \
  -v supplychain-data:/app/.runtime -v supplychain-bge:/models/bge:ro \
  -e AGENT_EMBEDDING_MODEL_DIR=/models/bge supplychain-agent:v2
curl --fail http://127.0.0.1:8765/v2/health
```

确保本地服务未占用端口，并等待就绪检查返回 200。真实 DeepSeek 需要在启动服务的进程中配置 `DEEPSEEK_API_KEY`，请求显式设置 `mode=llm`；Docker 用 `--env DEEPSEEK_API_KEY` 转发已有变量。程序不自动读取 `.env`，不要将凭据写入源码或命令参数值。完整说明见 [运行指南](running.md)和 [Demo 指南](demo.md)。

## 测试与实验结果

| 检查 | 结果 | 时间/口径 |
| --- | --- | --- |
| 完整 pytest | **318 passed，2 warnings，9.38 秒**；无失败或跳过 | 本轮实跑，启用真实 embedding 集成测试 |
| 代码规范 | Ruff check / format check 通过，59 个 Python 文件 | 本轮实跑 |
| Docker 镜像 | 当前镜像 ID 与上轮构建并验证的镜像一致 | 本轮核对；未宣称本轮重新构建 |
| Docker runtime | 断网运行、BGE/FAISS/RRF、Solver/Validator、重启和 Trace 持久化通过，安装源码 hash 匹配 | 本轮重新执行；使用独立测试容器/数据库卷 |
| Live DeepSeek smoke | 上轮单次真实请求 completed、optimal、valid | 本轮主动不注入 Key，未再次调用 live API；不是新的 24 条评测 |
| 固定检索留出 12 条 | lexical Hit@1 10/12、Hit@3 11/12；semantic 8/12、12/12；hybrid 11/12、12/12 | 历史结果，上轮相同数据复跑确认；本轮未重跑 |
| 固定 Agent 留出 24 条 | lexical 22/24、semantic 21/24、hybrid 22/24 | 历史真实模型评测，本轮不改数字 |
| 当前项目快照 | 未发现确认真实凭据、私人联系方式、个人路径或禁止发布的运行产物 | 范围为项目已跟踪文件，不包含父仓库的私人材料 |

318 项为原有 313 项加 5 项 Demo 边界测试，不代表业务成功率提升。两条 warning 是既有 Starlette/httpx 与 anyio 弃用提示。离线规则、实际 LLM、单次 smoke 和固定留出评测使用不同口径，不互相替代。

## 已知限制

- 合成数据、小型固定留出集，由同一 AI 辅助流程编写；不是独立大规模 benchmark。
- Hybrid 的 Agent E2E 与 lexical 持平；两个既有失败案例涉及显式参数与最终政策引用，未假装修复。
- 单期确定性模型，不做需求预测、多期库存或多供应商分配。
- Validator 检查建模条件下的可行性，不证明现实所有约束已覆盖，也不独立证明全局最优。
- Live 依赖外部 DeepSeek；同步工具没有进程级硬超时；SQLite Trace 不等于防篡改或长期任务恢复。
- Docker 仅本地 Linux ARM64 验证，没有云端、生产流量或生产并发验证。
- 干净导出目录可运行应用和测试；依赖旧 commit 的历史 manifest 校验需在私有原仓库执行。

## 发布前检查项

### 已完成

- [x] 审计全部本地分支/ref/reflog 及全部本地对象，不仅检查工作区。
- [x] 列出 29 个历史风险路径及所在 commit，确认当前文件已脱敏而旧历史仍保留。
- [x] 识别额外非 commit 快照中的简历、联系方式、ZIP 与缓存；不虚构所属 commit。
- [x] 检查 17 PDF、10 DOCX、3 ZIP 及嵌套文档；不在报告中输出命中原值。
- [x] 区分测试假凭据、脱敏占位符与实际风险；未发现确认真实 token/private key。
- [x] README、Demo、docs、测试口径和运行方式与当前实现核对。
- [x] 完整测试、Ruff、Docker 离线和持久化检查通过。
- [x] 已有评测数据与历史结果未改动，原有未跟踪私人材料不纳入提交。
- [x] 无超过本次 5 MiB 复核阈值的本地历史 blob；数据库/模型权重不在当前项目 Git 中。
- [x] 只提交本次审计文档，不修改历史、不 GC/prune、不 push。

### 发布前仍需完成

- [ ] **选择干净导出方案**：仅导出最新 `HEAD:supplychain-agent`，在新目录新仓库建立真实当前日期的 initial commit；不复制原 `.git` 或整个求职仓库。
- [ ] **确认公开作者身份**：现有 commit 带非 GitHub noreply 作者/提交者邮箱。新公开仓库的姓名与邮箱由用户确认，不自动沿用私人信息。
- [ ] **确认并添加 LICENSE**：当前没有项目许可证。GitHub 可见性不等于已授予完整的开源复用许可；不代用户作授权决定。[官方说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)。
- [ ] 核对第三方依赖、模型和展示资源的授权/署名要求；模型权重继续不纳入 Git。
- [ ] 在最终干净导出目录复跑 Quick Start、测试和 Demo，扫描全部待提交文件与新 initial commit。
- [ ] 确认 GitHub 目标仓库、描述、可见性和首次 push 授权；本轮不建立远程或推送。

现有 `public-release/` 属于单独版本，本轮不覆盖，也不默认它已同步本次工程化修改。清理方案细节见 [历史审计第 5 节](git-history-audit.md)。

```text
ENGINEERING_READY = YES
CURRENT_PROJECT_SNAPSHOT_SCAN = PASS
EXISTING_HISTORY_READY = NO
OPEN_SOURCE_LICENSE_READY = NO
READY_TO_PUSH = NO
HISTORY_REWRITTEN = NO
PUSH_EXECUTED = NO
```
