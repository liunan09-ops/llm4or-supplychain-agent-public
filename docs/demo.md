# V2 本地演示与截图

`scripts/demo_v2.py` 是现有 V2 `Agent.run` 的展示封装，没有增加业务工具、规划策略或求解逻辑。使用已有 Rich 依赖和 Python 标准库，不增加前端或额外依赖。

## 最短演示

```bash
make install-lexical
make demo-v2
```

默认输入为“先查询库存，再预算9000元，电机不能缺货”。默认 **demo + lexical**：自然语言使用现有规则句式解析，明确显示 `offline rules / no LLM`。RAG、MILP、Validator 和 SQLite 均实际执行，不是预制回放。

已按运行指南准备模型时，可展示 hybrid：

```bash
.venv/bin/python scripts/demo_v2.py --backend hybrid --output-dir .runtime/my-demo-01
```

支持 `--message`、`--mode demo|llm`、`--backend lexical|semantic|hybrid`、`--model-dir`、`--output-dir`。输出目录必须尚不存在；默认自动生成独立目录。每次运行创建自己的合成数据库，不改动日常 API 数据库。

## 截图与证据

| 输出 | 用途 |
| --- | --- |
| `demo.svg` | 可直接放入 GitHub README；使用本地字体，不访问字体 CDN；已修正中文宽字符宽度 |
| `demo.html` | 用浏览器打开后截图；无脚本、无外部服务依赖 |
| `response.json` | 原始 Response，包含实际工具调用、结果、引用和状态 |
| `trace.json` | 从 SQLite 读回的完整运行记录，含输入与快照 |
| `business.sqlite3` / `runs.sqlite3` | 本次合成数据与审计存储，仅本地保留 |

README 中的[截图](assets/demo-v2.svg)与[响应](assets/demo-v2.response.json)来自同一次 `demo + hybrid` 执行，采购支出 8992、预算 9000、validator valid、139 checks，LLM calls=0。这是单个展示用例，不改变任何 benchmark 数字。SVG 已实际渲染检查中文、表格与边界。

## 面试时演示三个分支

```bash
.venv/bin/python scripts/demo_v2.py --message '查询库存：电机'
.venv/bin/python scripts/demo_v2.py --message '预算0元，电机不能缺货'
.venv/bin/python scripts/demo_v2.py --message '先查询库存，再预算9000元，电机不能缺货'
```

分别展示：查询不调用 Solver；不可行时保留原约束、不认证方案；可行且验证通过后才展示采购表。解释表中 Available 包含计划窗口内在途，Purchase cost 是采购支出，不是总目标成本。

真实模型演示需预先配置进程凭据，再运行 `--mode llm --backend hybrid`。成功或失败均保存实际结果；未提供 Key 不切回 demo。正常业务结果（completed / infeasible / needs_clarification / rejected）退出码为 0，Agent 执行失败为 1，准备失败或输出目录冲突为 2。

分享之前核对实际输入和结果；只公开合成演示，不上传自己的数据库、凭据或带私人信息的请求。展示时如实说明哪些工作借助 AI 完成，以及自己能独立解释的设计与验证。
