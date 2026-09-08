# Docker Runtime Verification · Final Release

**PASS：实际 build、容器 HTTP、离线和真实 DeepSeek 全链路、BGE/FAISS、重启均完成。** 仅验证本地 Docker Desktop Linux ARM64；没有云端或生产部署证据。

基线 `e10ce8f9766337b8e42f83b2d057722d51a0612d` 在验证时未改变；历史缺少 Docker 的记录仍保留于 [旧检测](evaluation/final/docker_runtime.json)，不把旧阶段写成成功。本轮原始证据在 [release](evaluation/release/docker/summary.json)。

## 环境、构建与必要修复

| 实际命令 / 项目 | 结果 |
| --- | --- |
| `docker --version` | exit 0；Docker 29.7.2，build a7dcaa6 |
| `docker info`（仅记录 ServerVersion / Architecture / OSType / OperatingSystem） | exit 0；29.7.2 / aarch64 / linux / Docker Desktop，daemon 正常 |
| `docker build -t supplychain-agent:v2 .`，原配置 | exit 0；但 `docker run --rm --network none --entrypoint python supplychain-agent:v2 -c 'import onnxruntime'` exit 1，实际缺 semantic 依赖 |
| 同命令，修复后 | exit 0；[完整构建日志](evaluation/release/docker-build.log) |
| image | Linux arm64；镜像 ID、Docker 报告的字节数见 [镜像审计](evaluation/release/image_audit.json)；不将压缩/磁盘占用混为内存需求 |
| 默认 semantic extra | `WITH_SEMANTIC=1`；仍允许显式 `0` 配合 lexical |
| 可复现依赖 | Python 3.12 base 和 uv 0.12.9 固定 multi-platform digest；`uv sync --frozen --no-dev --no-editable --extra semantic`；无新增 Python 依赖、lock 不变 |
| 启动 | 非 root UID/GID 10001；uvicorn `0.0.0.0:8765`；HEALTHCHECK 请求 `/v2/health` |

额外只复制已有模型准备脚本，预建有正确权限的 `/models/bge`；`.dockerignore` 补充排除 release 证据。镜像没有 `.env`、业务数据库或下载的 BGE 权重；ONNX Runtime wheel 自带的 3 个微型示例模型单独列出，不冒充 BGE。全 layer 扫描未匹配当前真实凭据。

## 干净模型和运行验证

模型准备在新建 Docker volume 内完成，未挂载宿主机源码、虚拟环境、数据库或模型缓存：

```bash
docker run --rm --name supplychain-release-prepare \
  -v supplychain-release-model-20260908:/models/bge \
  --entrypoint python supplychain-agent:v2 \
  scripts/prepare_embeddings.py --model-dir /models/bge
python3 scripts/verify_docker_runtime.py \
  --model-volume supplychain-release-model-20260908 --output evaluation/release/docker
```

两条命令 exit 0。第一条使用固定公开 HTTPS revision 下载 95,291,718 bytes，3 个文件 SHA-256 全通过，[准备日志](evaluation/release/docker-model-prepare.log)。第二条只依赖宿主机 Python 标准库和 Docker CLI，详细命令及 exit code 见 [commands](evaluation/release/docker/commands.json)。准备需外网；随后本地模型推理不联网，不隐式下载，不回退 lexical。

| 验证 | 实际证据 |
| --- | --- |
| `/health`、`/v2/health` | HTTP 200、status ok；默认 backend hybrid；[离线记录](evaluation/release/docker/offline.json) |
| keyless/offline Agent | 容器 `--network none`，无 DeepSeek/LLM key，库存查询 completed；不是 mock LLM 冒充真实调用 |
| `/optimize` | 预算 9000，5 类工具依次完成；solver optimal，独立 Validator valid、139 checks、0 violations；LLM calls 0 |
| BGE / ONNX | BGE-small-zh-v1.5 FP32，CPUExecutionProvider，实际 query shape `[1,512]`、L2 norm≈1；[推理证据](evaluation/release/docker/embedding.json) |
| FAISS / semantic / hybrid | 实际执行三路 query，各返回 3 个原文片段；重算每条 RRF contribution 与总分相符 |
| clean wheel | 容器 site-packages 内所有项目源码/政策文件 SHA 与当前源码逐文件相同；依赖版本记录，无宿主 venv 注入 |
| stop → start | 再次 HTTP 200、离线库存和优化 completed；snapshot/index manifest 相同，重启前 request ID 仍可查；[重启记录](evaluation/release/docker/restart.json) |
| 宿主 HTTP | live 容器只绑定 `127.0.0.1` 临时端口，宿主 `/health` HTTP 200 |

## 真实 DeepSeek 示例

请求：`先查询库存，再预算9000元，电机不能缺货`。既有合法 `DEEPSEEK_API_KEY` 仅通过 `--env DEEPSEEK_API_KEY` 转发，不出现在命令字面值、build 参数、image 或证据中。

[真实 HTTP 和完整 trace](evaluation/release/docker/live.json)：HTTP **200**，`query_then_optimize`，预算 9000、protected SKU MOTOR；工具为 `inventory_query → supplier_query → policy_retrieval → replenishment_optimizer → solution_validator`。Hybrid 原文证据包含预算、审批、应急和服务规则。求解 **optimal**，采购成本 **8992**（合成货币金额），Validator **valid / 139 checks / 0 violations**，最终 **completed**。

该次 `deepseek-v4-flash` 逻辑模型调用 **7**、HTTP 尝试 **7**、API tokens **16846**，服务端耗时 **8821.427 ms**。这是单次容器冒烟证据，不是性能分位数，不并入既有 24 条 E2E 分母，不改写 lexical 22/24、semantic 21/24、hybrid 22/24 的实验。

最终 README 纳入镜像后又执行一次完整复验，命令将输出改为 `evaluation/release/docker-final`，exit 0；[最终镜像运行记录](evaluation/release/docker-final/summary.json) 与 [镜像审计](evaluation/release/image_audit.json) 的 image ID 一致：`sha256:36e1916b64c5623d17057ec6082e40c0d77ebd536d24b9f8c81671ed7eeb2a04`，Docker Size **167,015,697 bytes**（约159.28 MiB）。第二次同一请求 HTTP200/completed、optimal、Validator valid/139 checks；8次模型调用、耗时10349.235 ms，其中 policy_retrieval 实际执行4次。两次成功冒烟都保留，调用次数波动不藏掉，不能当作新增独立测试集。

## Reviewer 复现和边界

面向陌生环境的完整命令见 [README Docker Quick Start](README.md#docker)。默认镜像已包含 semantic 依赖；只需公开模型下载和可选 DeepSeek 凭据。SQLite 用命名卷持久化，模型卷运行时只读，启动重建小型 FAISS 内存索引。

验证脚本清理它创建的临时容器和 SQLite 卷；保留请求的 image 和公开模型卷。脚本输出目录必须新建，避免覆盖旧证据。API 模型输出具有非确定性，后来请求若失败应保留失败，不能保证永远 completed。当前仅本地合成数据验收，无生产鉴权、企业流量、负载测试或高可用结论。
