# 代码与发布质量检查（2026-09-18）

范围：当前 `supplychain-agent/` 项目；本轮不修改核心 Agent、MILP、Validator、检索实现或固定评测数据。

| 检查 | 结果与口径 |
| --- | --- |
| Python 规范 | `make lint` 通过：Ruff check 与 format check，59 个 Python 文件 |
| 完整测试 | 在本轮新建的干净虚拟环境运行 `make test`：318 passed，0 failed / skipped，9.31 秒；保留 2 条既有依赖弃用警告 |
| 新增测试来源 | 原有 313 项 + Demo 的 5 项执行/展示边界测试；没有改动原测试以抬高通过数 |
| 原评测回归 | V1 36 条、V2 demo 38 条逐例评分不变；V2 demo held-out 仍为 17/24 |
| 检索复跑 | 同一开发集 6 条与留出集 12 条；三路 Hit/Recall 与历史值一致，hybrid Hit@1 11/12、Hit@3 12/12、Recall@3 0.9583 |
| 文档一致性 | 运行方式按现有代码与真实 HTTP 检查核对；区分 V1/V2、demo/llm、lexical/hybrid |
| 展示导出 | SVG 实际渲染检查，中文无重叠；HTML/SVG 与 JSON 来源于同一次真实本地执行 |
| 大文件 | 项目已跟踪文件无超过 5 MiB 的文件；最大既有证据文件约 1.09 MiB，新 Demo 资源远小于此阈值 |
| 忽略规则 | 扩充数据库、模型权重、压缩包、缓存与私钥扩展名；`.env.example` 仍可跟踪 |

## 类型与接口

新增展示脚本的函数入参与返回值有类型注释，输入继续使用现有 `Request` / `Response` Pydantic 模型。工具参数 schema、非法字段拒绝与响应类型由原有测试覆盖。现有核心内部仍有动态结构及未完全注解的函数；本轮未做批量类型重构，**没有运行或声称通过全项目 strict mypy/pyright**。

## 敏感信息与快照边界

使用现有 `scripts/audit_public_repo.py` 检查暂存区、工作文件与项目可达历史：凭据模式、当前配置凭据、私人邮箱/电话、本机路径、私钥与禁止文件。Demo 使用自动 seed 的合成业务数据；仅纳入审阅过的 SVG 与合成 JSON，数据库及运行输出留在 `.runtime`。

模式扫描不是对任意秘密的数学保证；结合 [既有人工审计](../PUBLIC_REPO_SAFETY_AUDIT.md) 核对数据来源。旧 Git 历史的本机元数据尚未脱敏，当前安全快照不等于整个仓库历史可直接公开。本轮未 push、未清理或改写旧历史。

检查不把 localhost 演示称为生产部署，不把离线规则 Demo 称为真实 LLM，不把同一小型合成留出集称为独立大规模 benchmark。
