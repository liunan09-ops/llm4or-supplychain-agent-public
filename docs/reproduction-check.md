# 本轮可运行性复核（2026-09-18）

本文件记录本轮实际执行，独立于 `evaluation/release` 的历史验收；不改写旧评测结果或 manifest。不是新的端到端 benchmark。

| 项目 | 本轮结果 |
| --- | --- |
| 宿主环境 | macOS / Apple Silicon，Python 3.12.14，uv 0.12.9 |
| 干净依赖安装 | 新建独立虚拟环境，`uv sync --python 3.12 --extra dev --extra semantic --frozen` 成功；锁文件未修改 |
| 固定 BGE 模型 | `prepare_embeddings.py --verify-only` 通过，3 个文件大小/hash 匹配固定 revision |
| 原有完整 pytest 基线 | 313 passed，0 failed / skipped，2 条既有依赖弃用警告，8.55 秒 |
| lexical / hybrid HTTP | 两种 backend 均通过 `smoke_v2.py`；包括 V1、V2 查询、优化、不可行、422 与 Trace 回放验证 |
| Docker build | Linux aarch64 构建成功；镜像 tag 为 `supplychain-agent:recruiting-check` |
| Docker 离线 | `--network none` 下查询、求解、验证通过 |
| 容器 BGE / FAISS / RRF | 真实 512 维归一化 embedding、三种检索、RRF 分数检查通过 |
| 容器重启 | 重启后原 Trace 仍可查询，SQLite 持久化通过 |
| 真实 DeepSeek 单次 smoke | HTTP 200，completed，solver optimal，validator valid（139 checks），6 次模型调用 |
| 源码对应关系 | 验证脚本确认容器安装的源码 hash 与当前项目源码一致 |

Docker 最初两次构建因依赖下载期间 TLS 连接中断失败。随后仅调整构建过程：使用 BuildKit 下载缓存、单并发下载和 120 秒读取超时。镜像基础 digest、依赖版本、锁文件及核心源码未修改；未关闭 TLS 校验。

## 复现入口

```bash
uv sync --python 3.12 --extra dev --extra semantic --frozen
.venv/bin/python scripts/prepare_embeddings.py --verify-only
RUN_EMBEDDING_INTEGRATION=1 .venv/bin/python -m pytest
AGENT_RETRIEVAL_BACKEND=lexical .venv/bin/python scripts/smoke_v2.py --output .runtime/check-lexical.json
AGENT_RETRIEVAL_BACKEND=hybrid .venv/bin/python scripts/smoke_v2.py --output .runtime/check-hybrid.json
docker build -t supplychain-agent:recruiting-check .
```

Docker 模型卷需先按 [README](../README.md#quick-start) 准备。再运行：

```bash
python3 scripts/verify_docker_runtime.py --image supplychain-agent:recruiting-check --model-volume supplychain-bge --output .runtime/docker-new-check
```

本轮复用了已校验的模型卷，没有宣称重新从零下载模型。live 使用当前进程中已有的凭据，没有复制凭据到文件。验证脚本清理了它自己创建的容器与数据库卷，保留镜像、模型卷。

原始本地输出保存在被忽略的 `.runtime/recruiting-http-lexical.json`、`.runtime/recruiting-http-hybrid.json`、`.runtime/recruiting-docker-check/`。它们没有覆盖固定留出集或历史证据，也没有加入 Git。公开复现请运行上述命令获得自己的输出；单次 live 成功不更新历史 22/24 的分子或分母。
