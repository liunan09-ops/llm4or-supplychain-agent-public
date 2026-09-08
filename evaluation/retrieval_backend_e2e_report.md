# 真实 DeepSeek Retrieval Backend E2E 对照

同一固定 24 条合成 Agent 留出请求；不是新增盲测或生产准确率。原 Core score 函数不改。
按请求轮换 lexical → hybrid → semantic 的执行起点，各自运行一次，降低固定先后顺序偏差；不消除模型随机性和服务缓存影响。

状态：completed；模型：deepseek-v4-flash。

| backend | E2E | intent | tools | args | retrieval | clarify | refuse | validator | p50/p95 ms | calls | tokens |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lexical | 22/24 | 23/24 | 23/24 | 21/24 | 2/2 | 4/4 | 2/2 | 5/5 | 3654.0/8060.1 | 93 | 149061 |
| hybrid | 22/24 | 24/24 | 24/24 | 22/24 | 2/2 | 4/4 | 2/2 | 6/6 | 4088.5/9275.5 | 100 | 182691 |
| semantic | 21/24 | 24/24 | 23/24 | 22/24 | 2/2 | 4/4 | 2/2 | 5/5 | 3726.1/8342.5 | 96 | 170610 |

工具选择/参数指标按请求计，包含状态机约束；retrieval 仅对有政策相关标注的问题计分。Validator 仅对实际校验调用计分。
Optimization feasibility 的分母是实际 optimizer 调用，包含预期 infeasible；预期不可行不是 Agent 失败。constraint_pass 则仅对已发布可行方案独立重验。
金额估计为 null：现有客户端没有保存可靠的缓存命中/未命中用量拆分及冻结价格表；token 是 API 报告值。

## lexical 失败与预期终态

Optimizer outcomes: `{'optimal': 5, 'tool_failure': 2, 'infeasible': 2}`

诊断标签（可重叠）: `{'argument_extraction_or_tool_argument_failure': 3, 'routing_failure': 1, 'tool_selection_failure': 1, 'llm_generation_failure': 1, 'expected_clarification': 4, 'expected_solver_infeasible': 2, 'expected_refusal': 2, 'expected_injected_tool_failure': 1}`

- **v2-test-13**：先看所有物料库存，再按预算9800元出补货建议。；标签 `routing_failure, tool_selection_failure, argument_extraction_or_tool_argument_failure, llm_generation_failure`。malformed_intent
- **v2-test-17**：计划周期7天，控制器不能缺货；标签 `argument_extraction_or_tool_argument_failure, expected_solver_infeasible`。BEARING：现货 40，在途 0，7 天窗口内可用库存 40，原始需求 150。[SQLite snapshot cc18a8ef96f0]
BELT：现货 15，在途 12，7 天窗口内可用库存 15，原始需求 90。[SQLite snapshot cc18a8ef96f0]
MOTOR：现货 8，在途 0，7 天窗口内可用库存 8，原始需求 30。[SQLite snapshot cc18a8ef96f0]
PLC：现货 4，在途 0，7 天窗口内可用库存 4，原始需求 10。[SQLite snapshot cc18a8ef96f0]
SENSOR：现货 20，在途 5，7 天窗口内可用库存 25，原始需求 65。[SQLite snapshot cc18a8ef96f0]
BEARING：供应商 SUP-B（approved），单价 16.0，MOQ 30，上限 180，交期 4 天。[SQLite snapshot cc18a8ef96f0]
BELT：供应商 SUP-B（approved），单价 28.0，MOQ 20，上限 100，交期 5 天。[SQLite snapshot cc18a8ef96f0]
MOTOR：供应商 SUP-A（approved），单价 220.0，MOQ 5，上限 40，交期 3 天。[SQLite snapshot cc18a8ef96f0]
PLC：供应商 SUP-C（approved），单价 460.0，MOQ 2，上限 12，交期 10 天。[SQLite snapshot cc18a8ef96f0]
SENSOR：供应商 SUP-A（approved），单价 65.0，MOQ 10，上限 80，交期 2 天。[SQLite snapshot cc18a8ef96f0]
[POL-SERVICE:01 · policies/service.md] POL-SERVICE 服务水平要求
## 服务与保护 SKU
最低服务水平约束要求每个 SKU 分别达到下限。结果中的总体满足率定义为一减总缺货量除以总需求量，仅用于结果展示；本版本不支持总体满足率硬约束。未指定服务水平时不额外添加下限。用户明确要求保护的 SKU 必须零缺货；数据中的 critical 标签本身不自动触发硬保护。禁止采购的 SKU 可以使用现有库存满足需求；禁止采购与零缺货保护可能同时导致不可行。
[POL-APPROVAL:02 · policies/approval.md] POL-APPROVAL 采购审批规则
## 异常处理
约束不可行时报告阻碍条件，由申请人决定是否提交新的预算或服务要求；不得自动放宽预算、MOQ、服务水平或改写供应商资质。
[POL-EMERGENCY:01 · policies/emergency.md] POL-EMERGENCY 紧急采购规则
## 紧急采购不豁免约束
停线风险、紧急采购或急单不自动豁免预算、供应商资质、MOQ、交期及供货上限。申请人需要给出具体 SKU、数量或服务要求。不支持通过加价自动缩短交期，也不支持未经审批的替代供应商。当前模型不包含加急运输决策。
[POL-LEAD:01 · policies/lead.md] POL-LEAD 交期与在途规则
## 计划窗口与在途
新采购交期超过计划窗口时不可订购；等于窗口时允许订购。在途订单仅统计 in_transit 且预计到货日不超过窗口的数量，已收货 received 不重复加到库存，cancelled 不计入。可用库存等于现货加窗口内在途到货。本版本是单期汇总模型，不保证逐日库存不为负，也不模拟需求在时间上的变化。
[POL-MOQ:01 · policies/moq.md] POL-MOQ 最小起订量规则
## MOQ 与供货上限
每个 SKU 的订购数量必须为非负整数；不采购时数量为零，采购时数量不得低于该 SKU 的最小起订量 MOQ，也不得超过供货上限。MOQ、价格及上限以供应商数据库为准，禁止模型自行编造。起订量不是整箱倍数约束；本版本没有包装倍数字段。
当前条件不可行，未放宽约束。充分证据：PLC 交期 10 天超过计划期 7 天，现有库存无法满足服务约束。；未自动放松预算、服务水平、保护清单、交期或采购限制。

## hybrid 失败与预期终态

Optimizer outcomes: `{'optimal': 6, 'tool_failure': 2, 'infeasible': 2}`

诊断标签（可重叠）: `{'argument_extraction_or_tool_argument_failure': 2, 'expected_clarification': 4, 'expected_solver_infeasible': 2, 'expected_refusal': 2, 'expected_injected_tool_failure': 1, 'llm_generation_failure': 1}`

- **v2-test-17**：计划周期7天，控制器不能缺货；标签 `argument_extraction_or_tool_argument_failure, expected_solver_infeasible`。当前条件不可行，未放宽约束。充分证据：PLC 交期 10 天超过计划期 7 天，现有库存无法满足服务约束。；未自动放松预算、服务水平、保护清单、交期或采购限制。
[POL-LEAD:01 · policies/lead.md] POL-LEAD 交期与在途规则
## 计划窗口与在途
新采购交期超过计划窗口时不可订购；等于窗口时允许订购。在途订单仅统计 in_transit 且预计到货日不超过窗口的数量，已收货 received 不重复加到库存，cancelled 不计入。可用库存等于现货加窗口内在途到货。本版本是单期汇总模型，不保证逐日库存不为负，也不模拟需求在时间上的变化。
[POL-APPROVAL:02 · policies/approval.md] POL-APPROVAL 采购审批规则
## 异常处理
约束不可行时报告阻碍条件，由申请人决定是否提交新的预算或服务要求；不得自动放宽预算、MOQ、服务水平或改写供应商资质。
[POL-SERVICE:01 · policies/service.md] POL-SERVICE 服务水平要求
## 服务与保护 SKU
最低服务水平约束要求每个 SKU 分别达到下限。结果中的总体满足率定义为一减总缺货量除以总需求量，仅用于结果展示；本版本不支持总体满足率硬约束。未指定服务水平时不额外添加下限。用户明确要求保护的 SKU 必须零缺货；数据中的 critical 标签本身不自动触发硬保护。禁止采购的 SKU 可以使用现有库存满足需求；禁止采购与零缺货保护可能同时导致不可行。
- **v2-test-22**：预算11000元，计划周期14天，传感器不能缺货，禁止采购PLC，轴承需求120件；标签 `llm_generation_failure`。answer_policy_citation_missing

## semantic 失败与预期终态

Optimizer outcomes: `{'optimal': 5, 'tool_failure': 3, 'infeasible': 2}`

诊断标签（可重叠）: `{'tool_selection_failure': 1, 'argument_extraction_or_tool_argument_failure': 2, 'execution_limit': 1, 'evidence_selection_failure': 1, 'expected_clarification': 4, 'expected_solver_infeasible': 2, 'expected_refusal': 2, 'expected_injected_tool_failure': 1}`

- **v2-test-02**：请按目前场景给出一份补货建议。；标签 `tool_selection_failure, argument_extraction_or_tool_argument_failure, execution_limit`。执行终止：max_replans。未发布未经确认的方案。
- **v2-test-11**：急单能换成没审批的供方吗，制度怎么说？；标签 `evidence_selection_failure`。[POL-APPROVAL:02 · policies/approval.md] POL-APPROVAL 采购审批规则
## 异常处理
约束不可行时报告阻碍条件，由申请人决定是否提交新的预算或服务要求；不得自动放宽预算、MOQ、服务水平或改写供应商资质。
- **v2-test-17**：计划周期7天，控制器不能缺货；标签 `argument_extraction_or_tool_argument_failure, expected_solver_infeasible`。当前条件不可行，未放宽约束。充分证据：PLC 交期 10 天超过计划期 7 天，现有库存无法满足服务约束。；未自动放松预算、服务水平、保护清单、交期或采购限制。
[POL-BUDGET:01 · policies/budget.md] POL-BUDGET 预算规则
## 预算硬约束
采购支出不得超过预算。预算只限制采购成本，不包括期末持有成本和缺货惩罚；优化目标则包含三者。未指定预算时使用场景默认预算；“预算降低百分比”相对于场景默认预算计算一次。绝对预算与相对预算变动不能同时指定。不得将降低总成本误解成降低预算。
[POL-APPROVAL:02 · policies/approval.md] POL-APPROVAL 采购审批规则
## 异常处理
约束不可行时报告阻碍条件，由申请人决定是否提交新的预算或服务要求；不得自动放宽预算、MOQ、服务水平或改写供应商资质。
[POL-EMERGENCY:01 · policies/emergency.md] POL-EMERGENCY 紧急采购规则
## 紧急采购不豁免约束
停线风险、紧急采购或急单不自动豁免预算、供应商资质、MOQ、交期及供货上限。申请人需要给出具体 SKU、数量或服务要求。不支持通过加价自动缩短交期，也不支持未经审批的替代供应商。当前模型不包含加急运输决策。

逐例原始请求、响应、trace、快照和评分见 [backend_e2e](backend_e2e)，路径与 SHA-256 索引见 [results](retrieval_backend_e2e_results.json)。
所有失败保留；此次不根据留出结果修改任何业务规则、模型提示词或标注。

## 最终解释补充（评分与原始记录不变）

- 三路共同的 v2-test-17 失败由显式 horizon_days=7 被省略引起；虽得到预期 infeasible，参数仍未与固定 ground truth 完全匹配，保留失败。
- lexical v2-test-13 是意图 schema 错误；hybrid v2-test-22 是最终必需政策引用缺失，不是检索索引或 solver 的直接故障。
- semantic v2-test-02 达重规划上限，v2-test-11 返回了不满足相关政策要求的最终证据。没有据此修改提示词、数据或 ground truth。
- optimizer_outcomes 的 tool_failure 是工具尝试未成功返回，包括在进入 solver 前被参数/时序校验拒绝的尝试；不能都叫 solver failure。按成功 solver 返回计，可行/全部结果为 lexical 5/7、hybrid 6/8、semantic 5/7；各含 2 个预期 infeasible。JSON 的 optimization_feasibility 按全部 optimizer 尝试计，分别为 5/9、6/10、5/10，两个分母都明确保留。
- Hybrid 有 6 次 Validator 通过，1 条随后最终引用失败未发布，所以已发布可行方案独立重验为 5/5。

最终默认选择与代价见 [RETRIEVAL_BACKEND_DECISION.md](../RETRIEVAL_BACKEND_DECISION.md)。
