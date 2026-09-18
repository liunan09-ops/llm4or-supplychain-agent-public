# 运行与复现指南

从项目目录执行命令。依赖以 `pyproject.toml` + `uv.lock` 为唯一依据，不维护第二份可能漂移的 requirements.txt。推荐 Python 3.12；首次安装需要访问包源。项目自带合成数据，首次初始化 SQLite 时自动 seed，不需要私有数据库或外部 CSV。

## 两种准备路径

| 目标 | 顺序 | 注意 |
| --- | --- | --- |
| 无模型、无 Key 演示 | `make install-lexical` → `make serve-lexical` | lexical 是真实词面检索；demo 使用规则解析 |
| 完整 hybrid | `make install` → `make prepare-model` → `make serve` | 首次显式下载固定 BGE 权重，之后本地推理 |
| 完整测试 | 完成 hybrid 准备 → `make test` | 包含 opt-in 真实 embedding 集成测试 |
| 无 embedding 测试 | `make install-lexical` → `make test-lexical` | 集成测试会跳过，不能声称全部测试通过 |
| 代码检查 | 安装 dev extra → `make lint` | Ruff lint + format check |

Make 的执行目标使用已安装的 `.venv`，不会在启动时重新同步或移除 optional dependencies。切换到 `install-lexical` 后，如需 hybrid，重新执行 `make install`。`make demo` 保留原 V1 演示，V2 HTTP 入口为 `/v2/agent`。

评测输出默认放入被忽略的 `.runtime/evaluations`。每次保留独立记录可设置 `OUTPUT_ROOT=.runtime/my-run-01`；不把输出写回已验收的固定证据。真实 LLM 评测需要有效凭据并产生调用用量。

## 环境变量

程序只读**进程环境**，不会自动加载 `.env`。模板为 [`.env.example`](../.env.example)，其中没有真实凭据。先设置环境，再启动服务；已启动的进程不会自动收到后来设置的变量。

| 变量 | 默认或含义 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 官方 DeepSeek 的凭据；demo 与本地 embedding 不需要 |
| `LLM_MODEL` | 当前代码默认 `deepseek-v4-flash`；历史实测模型，不承诺供应商永久提供 |
| `LLM_BASE_URL` | 默认官方 DeepSeek `/v1` 接口；兼容服务必须显式配置 |
| `LLM_API_KEY` | 兼容服务的专用凭据；显式提供时优先使用，禁止误用其他服务的 Key |
| `AGENT_RETRIEVAL_BACKEND` | API 默认为 `hybrid`，可选 `lexical` / `semantic` |
| `AGENT_EMBEDDING_MODEL_DIR` | 默认项目 `.runtime/models/bge-small-zh-v1.5`；Docker 示例为 `/models/bge` |
| `AGENT_AUDIT_PATH` | 默认 `.runtime/runs.sqlite3` |
| `AGENT_BUSINESS_PATH` | 默认与审计库同目录的 `business.sqlite3` |
| `RUN_EMBEDDING_INTEGRATION` | 测试用：显式设置 `1` 才运行真实 embedding 集成测试 |

路径相对于启动进程的工作目录解析。SQLite 目录须可写，模型目录可只读。不要把 Key 写进 README、截图、命令行参数或 Git。

## 启动后的验收

1. `GET /health`：基础存活状态。
2. `GET /v2/health`：业务数据、政策索引与 Trace 存储就绪；等待 HTTP 200 再发请求。
3. `POST /v2/agent`：`{"message":"查询库存：电机","mode":"demo"}`。
4. `POST /optimize`：`{"parameters":{"budget":9000}}`，检查求解状态及 `result.validation.valid`。
5. 从响应头 `X-Request-ID` 或响应体取运行编号，调用 `GET /v2/runs/{request_id}` 查看轨迹。

自动真实 HTTP 检查使用临时数据库，不污染日常运行记录：

```bash
AGENT_RETRIEVAL_BACKEND=hybrid .venv/bin/python scripts/smoke_v2.py --output .runtime/http-check.json
```

## Docker

完整构建、准备模型卷、启动命令见 [README](../README.md#quick-start)。使用非 root 用户运行，SQLite 卷持久化、模型卷只读。不要与本地服务同时占用 8765 端口，也不要重复使用正在运行的容器名称。

构建使用 BuildKit 的 uv 缓存挂载，并限制为单个并发下载、120 秒读取超时，以降低受限网络下重复下载的成本；仍校验锁文件中的版本和 hash，不关闭 TLS 校验。uv 参数含义见[官方环境变量文档](https://docs.astral.sh/uv/reference/environment/)。遇到网络中断可重试同一构建命令，缓存不进入运行镜像。

可用已有的验证脚本检查断网运行、真实 embedding、重启与 Trace 持久化：

```bash
python3 scripts/verify_docker_runtime.py --image supplychain-agent:v2 --model-volume supplychain-bge --output .runtime/docker-check-01
```

输出目录必须尚不存在。脚本只移除它自己新建的测试容器和数据库卷，保留镜像、模型卷；有 `DEEPSEEK_API_KEY` 时还会执行一次真实请求，缺少 Key 时明确记录 live 未运行。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| hybrid 启动失败 / 找不到模型 | 安装 semantic extra，执行 prepare 与 `--verify-only`；或显式选择 lexical |
| Docker daemon 无法连接 | 启动 Docker Desktop，先确认 `docker info` 成功 |
| 端口已占用 | 停止自己之前启动的服务，或更换端口；不强行终止未知进程 |
| live 提示凭据或模型错误 | 检查启动进程的变量、供应商端点与账号可用模型；不会自动降级成 demo |
| 修改 `.env` 后无效 | 本项目不自动读取该文件，需要导出进程变量并重启 |
| 历史 release 校验与新文档不一致 | 历史 manifest 绑定当时快照，不改写旧 hash；本轮复现结果另行记录 |

历史大样本或生产性能未被验证。干净快照可以运行项目；依赖旧 Git 锚点的历史校验脚本不适用于无历史的导出目录。
