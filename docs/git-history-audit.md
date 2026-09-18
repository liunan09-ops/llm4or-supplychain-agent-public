# Git 全历史与本地对象库发布审计

审计基线：`supplychain-agent-v2` / `0396f2d94f070a3bc3ccf21a19670f4b8db9c1ac`。本报告创建于 2026-09-18，统计对应本次文档提交之前。只读审计；没有 rewrite、reset、rebase、GC/prune、reflog expire 或 push。

**结论：当前项目快照可作为干净发布源；不能把现有分支历史或整个本地仓库直接公开。** 工程检查通过，历史隐私与开源授权仍需处理。报告不复制任何 Key、联系方式、作者邮箱或本机路径的原值。

## 1. 审计范围与方法

| 范围 | 结果 |
| --- | --- |
| 本地分支 | `main`、`supplychain-agent-v2`、`agent-runtime-platform`；没有本地 tag 或 remote-tracking ref |
| refs / reflogs / 本地 commit 对象 | 均覆盖 17 个 commit；未发现额外本地 commit 对象 |
| 本地完整对象库 | 17 commit、224 tree、669 blob，共 910 个对象 |
| commit 快照 | 435 个历史路径，556 个不同 blob |
| 额外对象 | 113 个 blob 不在现存 17 个 commit 的任何快照中；107 个可从其他 tree 还原相对文件名，6 个无法还原路径 |
| 容器检查 | 17 PDF、10 DOCX、3 ZIP；PDF 全页文本、DOCX XML、ZIP 成员及嵌套文档检查，无提取错误 |
| 大文件阈值 | 本次将 >5 MiB 作为人工复核阈值，不是 GitHub 硬限制；0 个超限 |
| 完整性检查 | `git fsck --full --no-reflogs --unreachable` 返回 0；报告 68 个 unreachable blob、67 个 unreachable tree |

使用 `git cat-file --batch-all-objects` 检查实际对象内容，并以 `git ls-tree` 关联每个 commit 的文件路径。检查 provider token、私钥、JWT、凭据字面量、带认证信息 URL、个人路径、邮箱/电话、机器名和禁止文件类型；另用当前进程中 1 个已配置凭据做精确匹配，仅保存命中计数。检查范围包含另一项目分支，但不修改它。

“不在 commit 快照中”与 fsck 的 unreachable 不是同一口径：fsck 还考虑 index 等根。报告只根据可证明的关联记录位置，不推断这些对象的创建者、时间或来源。普通分支 push 不会因此自动传输所有本地孤立对象；复制整个 `.git` 或混入其他快照则会扩大暴露面。

## 2. 分类结论

| 类别 | 发现 | 是否需要处理 |
| --- | --- |
| 真实 API Key / token / private key | 原始对象、提取文档与压缩包未发现已确认真实凭据；已配置凭据精确匹配为 0 | 没有证据要求因本仓库扫描结果轮换 Key；不能替其他聊天记录或外部文件背书 |
| credential / Bearer 字面量 | 命中均位于 MockTransport、monkeypatch、错误脱敏测试或其归档副本；是测试占位符 | 不应误删相关测试 |
| 个人绝对路径 | 17 个已提交文件的旧版本含本机路径 | 发布历史前需移除/脱敏；当前版本已脱敏 |
| 机器 hostname | 12 个 JUnit 文件的旧版本含机器名 | 同上；当前 redacted placeholder 不算敏感命中 |
| commit 作者信息 | 17 个 commit 均有 author/committer 邮箱，均不是 GitHub noreply 地址 | 由用户确认是否公开；新仓库应使用已确认的公开身份 |
| 简历/联系方式/照片与缓存 | 额外非 commit 快照对象存在简历与生成资料；28 个 PDF/DOCX/ZIP 容器的提取内容命中联系方式候选 | 不得包含在项目公开包或共享的 `.git` 中 |
| ZIP / DOCX 容器 | 3 个交付/求职 ZIP、10 个 DOCX；不属于现存 commit 历史 | 从公开版本排除，不声称它们曾属于某个 commit |
| 数据库 / 模型权重 / 真 `.env` | 未在被检查的对象路径、文件特征及压缩成员中发现；`.env.example` 为空值模板 | 继续保留忽略规则；不扫描或公开本地运行目录 |
| 大文件 | 最大本地 blob 1,186,464 bytes（字体缓存），最大 commit 可达 blob 1,142,214 bytes（评测 JSON） | 无超限项；缓存仍需排除，与大小无关 |

原有 `docs/resume_notes.md`、`RESUME_AGENT_V2_EVIDENCE.md` 等名称含 resume 的 Markdown 是项目说明，未因文件名直接判定为含私人简历。邮箱安全测试样例、脱敏 hostname 与扫描正则本身均已人工排除误报。

## 3. 可归属 commit 的风险文件

下表为全部 29 个历史风险路径。路径为仓库相对位置，不包含本机用户名。当前 HEAD 的相同文件已脱敏，但旧版本仍可从下列 commit 读取。各风险 blob 的完整 SHA 与 commit 全 SHA 见 [机器明细](git-history-audit.json)。

| 风险文件 | 风险类型 | 含风险版本的 commit | 是否需清理 |
| --- | --- | --- | --- |
| `supplychain-agent/evaluation/evidence/pytest-baseline.xml` | 机器名 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/evidence/pytest-final.xml` | 机器名 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/evidence/pytest-phase1.xml` | 机器名 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/evidence/pytest-phase2.xml` | 机器名 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/evidence/pytest-phase3.xml` | 机器名 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/evidence/pytest-phase4.xml` | 机器名 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/evidence/pytest-phase5.xml` | 机器名 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/evidence/pytest-phase6.xml` | 机器名 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/evidence/pytest-phase7.xml` | 机器名 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/final/pytest-final.xml` | 机器名 | `e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/final/regression/v1_rules_dev/report.json` | 个人路径 | `e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/final/regression/v1_rules_test/report.json` | 个人路径 | `e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/final/regression/v2_demo_dev.json` | 个人路径 | `e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/final/regression/v2_demo_heldout.json` | 个人路径 | `e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/semantic_v2/pytest-baseline.xml` | 机器名 | `f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/semantic_v2/pytest-final.xml` | 机器名 | `f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/semantic_v2/regression/v1_rules_dev/report.json` | 个人路径 | `f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/semantic_v2/regression/v1_rules_test/report.json` | 个人路径 | `f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/semantic_v2/regression/v2_demo_dev.json` | 个人路径 | `f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/evaluation/semantic_v2/regression/v2_demo_heldout.json` | 个人路径 | `f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/reports/first-test-llm/report.json` | 个人路径 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/reports/first-test-rules/report.json` | 个人路径 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/reports/llm-dev-v1.1/report.json` | 个人路径 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/reports/llm-dev-v1.2/report.json` | 个人路径 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/reports/rules-dev-v1.1/report.json` | 个人路径 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/reports/rules-dev-v1.2/report.json` | 个人路径 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/reports/rules-dev-v1/report.json` | 个人路径 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/reports/v2-regression-rules-dev/report.json` | 个人路径 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |
| `supplychain-agent/reports/v2-regression-rules-test/report.json` | 个人路径 | `ad58e78b`、`f85e98b0`、`e10ce8f9` | 是，若公开旧历史；干净导出可绕开旧 blob |

风险集中于：

- `ad58e78bcd98b06510bbca6f8f803f96c961e21f`：Core 历史数据集路径/JUnit。
- `f85e98b078061414b95027612f00c5ebf3b3d92c`：继续包含 Core 风险并新增 Semantic 阶段记录。
- `e10ce8f9766337b8e42f83b2d057722d51a0612d`：继续包含之前风险并新增 Final 阶段记录。
- `fb31ff2b9725f1f8bcdc2f55a1996a09515b15bf` 之后当前文件的字段已脱敏，**并未删除上述旧 commit/blob**。

作者/提交者邮箱风险对应全部 17 个 commit（完整列表见 JSON 的 `commits`）。它不属于某个源码文件；本轮新增审计提交继续使用现有 Git 身份，不擅自修改作者、日期或配置。

## 4. 无法归属现存 commit 的额外对象

这些对象位于本地 Git object database，但没有现存 commit 包含它们。**所在 commit = N/A**；不得杜撰 commit 或历史时间。下表列代表定位，JSON 的 `non_commit_snapshot_objects` 列出全部 113 个对象、可恢复文件名与样本 tree SHA。

| 风险文件/材料 | 代表 blob | 所在 commit | 处理 |
| --- | --- | --- | --- |
| `SupplyChain-Agent_V2_源码与证据.zip` | `db4d3cf58f4eb99f5a4b8e542f78c1f99da6e6b4` | N/A | 包内旧 report 有个人路径；排除整个交付包 |
| `SupplyChain-Agent_项目交付.zip` | `57aed4cc6f762cf25311e1b92a60c81f4b7c90c9` | N/A | 同上，不加入公开 Git |
| `秋招投递材料_20260907/刘楠_2027秋招投递材料.zip` | `a6ec894c722b9034cd9cb4e2d3fb68891231292d` | N/A | 包内网申文本等含联系方式；排除 |
| `优化版简历/刘楠_运筹优化算法_2027届_优化版.pdf` | `17c481bf4e2b0c9ae267e75d7b43dc9a39e89310` | N/A | 个人简历；排除 |
| `2027_CAMPUS_RECRUITING_PACKAGE/刘楠_2027届_大模型应用与Agent研发.pdf` | `ec2eff59802d5fd3e463772a40ec61cbb42086b5` | N/A | 多个历史内容版本均应排除 |
| 同求职包的可编辑 DOCX | `194bc32d9aa708ceac161f772c1df5d1a9dd5f8b` | N/A | 提取 XML 可见联系方式；排除 |
| 简历构建脚本、网申文本、审核文档 | `30d7fe7a086a3cf340031facb1709fa3c25f50af` 等 | N/A | 可能含个人联系方式/路径；不混入项目包 |
| `tmp/resume_20260907/` 渲染图、字体缓存、日志 | `04929bd73d77e83a6c324a70420ff0754c2d5945` 等 | N/A | 本地中间产物；排除，不执行删除 |

上述 ZIP 中检查了 201 个普通成员及嵌套的 2 个 PDF、2 个额外 ZIP 容器（DOCX）。未发现真实凭据；没有把 ZIP 内部文件虚构为独立 Git commit。照片、字体和其他二进制未做 OCR/隐写分析，因此不对其视觉内容给出“绝对无秘密”保证。

## 5. 清理方案（仅方案，未执行）

### 推荐：从当前已审计项目树建立新的独立公开仓库

1. 使用本次审计文档提交后的 `HEAD:supplychain-agent` 做只读导出，只取跟踪的项目文件；不复制父仓库、`.git`、其他项目或 untracked 文件。
2. 在全新目录中再次审阅文件清单、隐私、依赖许可与展示数字。不要覆盖或假定既有 `public-release/` 已包含本轮更改。
3. 用户确认公开作者身份和 LICENSE 后，再初始化全新 Git repository，用真实当前时间建立 initial commit。不要 backdate，也不继承旧对象库。
4. 在导出目录按 README 跑测试、Docker 与 Demo；历史 Git 锚点校验需保留原仓库，仅作为内部审计依据。
5. 新仓库 secrets 扫描与 staged 清单通过后，再单独确认远端仓库和 push。当前轮不执行。

### 备选：保留项目历史并脱敏

只在用户明确选择后，在一次性副本中评估历史过滤工具；先隔离 supplychain-agent 历史，再逐个处理 29 个文件的机器元数据，并单独决定作者信息。过滤会改变 commit SHA，现有 release manifest/历史锚点校验也可能失效，需要保留私有旧仓库及旧新映射，而不能悄悄改数字或伪造时间。完成前不触碰当前共享 worktree、不 force-push。

不建议用删除当前文件、修改 `.gitignore` 或添加一次新 commit 代替历史清理。也不运行本地 `git gc --prune`：共享对象可能被其他 worktree/index 使用，这不是生成公开版本的必要步骤。

## 6. 当前分支 release 判断

| 项目 | 判断 |
| --- | --- |
| README | PASS：定位、架构、流程、运行、Demo、指标口径和限制齐全 |
| Docker | PASS：当前镜像 ID 与已验证记录相同；本轮再次验证断网、模型、重启与 Trace 持久化 |
| Demo | PASS：真实调用现有 Agent，模式明确，截图与 JSON 同源，覆盖失败展示边界 |
| docs | PASS：运行、演示、质量、面试、历史评测说明可追溯 |
| tests | PASS：本轮 318 passed，2 条既有依赖弃用警告；Ruff 59 文件通过 |
| 当前项目快照 | 扫描 PASS；不等于历史安全，不涵盖父仓库的私人材料 |
| 开源授权 | PENDING：未发现 LICENSE，pyproject 未声明项目许可证；不代用户选择 |
| 直接 push 当前分支 | NO：仍携带可达旧隐私 blob 与未确认的作者信息 |

项目可公开展示与授予开源复用权限是两个决策；许可证由用户确认。[GitHub 官方许可证说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)。

## 7. 边界与原始证据

本轮没有联网验证任何凭据是否有效，没有 fetch 或审计远端服务器、外部备份、其他独立 Git 仓库。正则、文件签名与文本提取无法证明任意混淆秘密不存在。作者邮箱仅记录存在性，未复制值。

本地原始中间结果位于被忽略的 `.runtime/pre-release-audit/`；公开可审阅的风险定位与计数为本报告及 JSON，均不含命中原值。发布操作清单见 [release-checklist.md](release-checklist.md)。
