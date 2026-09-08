# Public Repository Safety Audit

**PUBLIC_REPO_SAFE = YES**，范围限定为本次审核后的 `supplychain-agent/` **当前发布快照**。不代表现有整个 `ln秋招` 仓库和全部历史均可直接公开；本轮没有 push、创建分支或改写历史。

## 审计范围与方法

对 Git index 的实际 blob、相同文件的工作区内容、当前分支可达的项目历史 blob 分别扫描；不只搜索磁盘文件。文件数量、凭据匹配结果和候选命中见 [机器审计](evaluation/release/public_audit.json)，脚本见 [audit_public_repo.py](scripts/audit_public_repo.py)。凭据使用环境中现值做精确匹配，仅保存计数，不输出值。另检查 provider token/private key 模式、邮箱、手机号候选、用户目录，并人工追溯 password/cookie/Authorization/Bearer 和业务数据的来源。

| 类别 | 判断 / 处理 |
| --- | --- |
| 真实 DeepSeek/OpenAI 风格 token、配置凭据 | 当前快照及已扫描历史未发现真实 token / private key / 已配置凭据；Docker 全 layers 也未匹配，[镜像审计](evaluation/release/image_audit.json) |
| `.env.example` | 空值和示例域名，合法 placeholder；没有复制真实 `.env` |
| `unit-test-secret-ONLY`、`test-key`、`unit-test-sensitive-key` 等 | tests 的 MockTransport / monkeypatch 测试假密钥；用于断言脱敏与认证失败，不是可用凭据 |
| Authorization / Bearer | 运行时从环境构造请求 header，以及测试断言；保存的 Agent trace 没有原始认证 header |
| password / cookie | 拒绝外泄的检测代码、伪造 userinfo URL 测试等；未发现真实密码、cookie 或会话值 |
| 邮箱 / 手机 | 邮箱候选来自 `custom.invalid`、userinfo URL 的安全测试，不是联系人；连续数字候选按上下文区分 hash/小数，未发现真实联系电话 |
| 本机路径 / hostname | 17 份旧 JSON 仅将 dataset/cases_path 改为项目相对路径，12 份 JUnit 仅替换 hostname；本轮输出同样清理。旧→新 hash 和受限变换见 [脱敏清单](evaluation/release/privacy_redactions.json) |
| ABB / 企业供应商、价格、订单 | 人工核对 data.py、database.py、policies、固定样本及真实 trace：5 SKU、SUP-A/B/C 与“合成供应商”名称、PO-* 演示订单、示例成本均来自本项目 synthetic seed；没有导入 ABB 文件或内部系统数据 |
| 模型 / DB / 缓存 / zip / 简历 | 不在本次 index 或 image 的项目内容中；模型只存在外部 volume/ignored runtime，zip、简历和项目外 untracked 保持原样 |

README 明确个人实践、synthetic/demo、AI-assisted、不是 ABB 内部系统、无 ABB confidential data。扫描与来源审核支持当前发布判断；不宣称用正则能够证明任意文件的商业保密属性。

## 隐私修复与历史证据

本轮不改变源码、测试、提示词、留出集答案、政策文本、72 条真实 E2E 记录或指标。29 份历史证据只改不参与评分的机器元数据，保留原 checkpoint 中的历史 manifest。新 [verify_release.py](scripts/verify_release.py) 从基线 Git blob 核实旧 hash，再验证脱敏仅为指定字段文本变换，并重新计分。旧验证脚本属于旧 checkpoint，不能将其全文件 hash 直接用于已脱敏快照。

**历史隐私未清理。** 旧 Git blobs 仍含旧机器路径/JUnit hostname，Git author 元数据也保留；没有因当前文件被脱敏就宣称历史被抹除。因此可以公开当前项目快照，**不建议把当前整个仓库及历史直接设为 public**。既有 untracked 简历和求职材料也不能混入公开仓库。

发布当前项目快照可在提交后执行只读导出（本轮不执行发布、不创建仓库）：

```bash
git archive --format=tar HEAD:supplychain-agent > /tmp/supplychain-agent-public.tar
```

这只导出已提交的项目树，不包含 `.git` 历史、项目外文件或 untracked 内容。陌生 reviewer 解包后可以使用 README 的 local/Docker Quick Start；历史锚点的完整 Git 审计需本地保留本分支历史。不要对现有整个仓库直接 push 来代替此范围明确的发布。
