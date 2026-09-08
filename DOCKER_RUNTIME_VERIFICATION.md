# Docker 实机验证记录

**Docker configuration implemented but runtime verification blocked because Docker is unavailable on the current machine.**

本机实际执行结果见 [docker_runtime.json](evaluation/final/docker_runtime.json)：

| 命令 / 检查 | 实际结果 |
| --- | --- |
| `docker --version` | exit code 127，`docker: command not found` |
| `docker info` | exit code 127，`docker: command not found` |
| `/Applications/Docker.app` / `Docker Desktop.app` | 不存在 |
| `/usr/local/bin/docker` / `/opt/homebrew/bin/docker` | 不存在 |
| image build / container startup / restart | 未执行，不能写为成功 |
| 容器内 `/health`、Agent、真实 LLM、BGE | 未执行，不能由本机测试替代 |

没有安装 Docker 或其他容器平台，也没有用模拟执行代替实测。该 blocker 不影响当前校招项目冻结，但“Docker 部署成功”不能写进简历。

## 已完成的静态检查

- Dockerfile 使用 Python 3.12、固定 uv 0.12.9、`uv.lock --frozen`、非 root 用户、持久运行目录与 `/v2/health` readiness 检查。基础镜像 tag 尚未锁 digest。
- 最小 image 仅安装 lexical 所需依赖，运行时必须显式设置 `AGENT_RETRIEVAL_BACKEND=lexical`；API 本身的发布默认值为 hybrid。新增 `WITH_SEMANTIC=1` 构建参数安装已经锁定的 semantic extra，拒绝其他参数值。这个配置尚未经过 Docker build 验证。
- 模型不在 build 阶段联网下载或烘焙进 image；semantic/hybrid 通过只读模型目录挂载和 `AGENT_EMBEDDING_MODEL_DIR` 加载，应用会验证固定文件 SHA-256。
- `.dockerignore` 排除 `.env*`、`.runtime`、虚拟环境、数据库、模型权重、缓存和体积较大的评测 trace；Dockerfile 没有 secret ARG/ENV、没有复制 `.env` 或密钥。
- 本次 Git 文件扫描未发现已配置 API Key。没有实际 image，不能宣称完成 image layer 的密钥检查。

## 具备 Docker 环境后可执行的命令（本机未执行）

```bash
docker build -t supplychain-agent:v2 .
docker run -d --name supplychain-agent-v2 \
  -p 127.0.0.1:8765:8765 -v supplychain-runtime:/app/.runtime \
  -e AGENT_RETRIEVAL_BACKEND=lexical \
  supplychain-agent:v2
curl --fail http://127.0.0.1:8765/health
curl --fail http://127.0.0.1:8765/v2/health
curl --fail http://127.0.0.1:8765/v2/agent -H 'Content-Type: application/json' \
  -d '{"message":"查询库存：电机","mode":"demo"}'
curl --fail http://127.0.0.1:8765/optimize -H 'Content-Type: application/json' \
  -d '{"parameters":{"budget":9000}}'
docker restart supplychain-agent-v2
curl --fail http://127.0.0.1:8765/v2/health
```

另建可选语义 image，并使用已下载且哈希验证的模型目录：

```bash
docker build --build-arg WITH_SEMANTIC=1 -t supplychain-agent:v2-semantic .
docker run --rm --name supplychain-agent-v2-semantic \
  -p 127.0.0.1:8766:8765 -v supplychain-semantic-runtime:/app/.runtime \
  --mount "type=bind,source=$(pwd)/.runtime/models/bge-small-zh-v1.5,target=/models/bge,readonly" \
  -e AGENT_RETRIEVAL_BACKEND=hybrid -e AGENT_EMBEDDING_MODEL_DIR=/models/bge \
  supplychain-agent:v2-semantic
```

需要验证真实 DeepSeek 时，由使用者已设置的进程环境通过 `--env DEEPSEEK_API_KEY` 传入；命令行不写密钥字面值。仍须实测依赖安装、镜像内容、容器健康、重启、真实请求和 BGE 推理后，才能更新本报告为通过。
