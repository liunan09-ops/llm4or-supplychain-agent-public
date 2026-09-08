# 供应链决策助手 · 工程回归评测

> 数据和业务成本均为合成示例。本集合不是公开基准；小样本结果不代表独立泛化能力或真实企业收益。

- 时间（UTC）：2026-09-08T15:11:11.622054+00:00
- 模式 / 模型：rules / 无模型调用
- 解析器来源：production
- 集合：test，12 条；标签：semantic-hardening-regression
- 协议版本：1.1；代码版本：0.1.0
- Git：e10ce8f9766337b8e42f83b2d057722d51a0612d；工作区有修改：True
- 源码 SHA-256：`5556e9cf1bc4aea1dceda2338bd17bf68b02e2029c7e289529f8339fb4ce347b`；运行期间源码变化：False
- 用例文件 SHA-256：`958643ed048dc3c7446f287748f88ac7a6e39adc33ad3b11eedab7c8a5a420fe`
- 原始冻结集一致：True

## 指标与分母

| 指标 | 实测值 |
| --- | --- |
| 系统动作正确率（成功解析） | 100.0% (12/12) |
| 系统严格意图正确率（成功解析，全部参数） | 100.0% (12/12) |
| 有模型请求的系统动作正确率（成功解析） | N/A (0/0) |
| 有模型请求的系统严格意图正确率（成功解析） | N/A (0/0) |
| 有模型请求的端到端严格意图成功率（含请求失败） | N/A (0/0) |
| 本地守卫动作正确率 | N/A (0/0) |
| 端到端动作成功率（全部用例） | 100.0% (12/12) |
| 端到端严格意图成功率（全部用例） | 100.0% (12/12) |
| 求解状态符合预期（要求状态的全部用例） | 100.0% (8/8) |
| 误触发求解（本应澄清/拒绝，除以求解尝试数） | 0.0% (0/8) |
| 安全执行（除以正常完成的求解调用） | 100.0% (8/8) |
| 不安全执行数 | 0 |
| 方案可行性校验（仅已返回可行方案） | 100.0% (7/7) |
| 语义正确且可行（仅已返回可行方案） | 100.0% (7/7) |

解析/API 错误：0；求解调用错误：0。
供应商逻辑调用 0 次，HTTP 请求尝试 0 次（含重试）；本地守卫处理 0 条；调用归因未知 0 条。
实际请求供应商的用例 0 条，其中解析/API 错误 0 条。
本地守卫的拒绝/澄清不计入模型请求子集；归因来自显式调用遥测，不根据零 Token 猜测。系统输出可能经过本地后置校验，不能解释为裸模型准确率。
调用失败不算模型回答，不进入成功解析正确率分母；在端到端指标中计为未成功。
安全执行同时要求完整意图匹配、求解正常结束，以及可行方案通过重新校验；正确报告不可行也算安全完成。
此处执行仅指本地求解器调用，本项目不发送采购订单、不付款。

解析延迟：{"count": 12, "mean_ms": 0.049, "p50_ms": 0.041, "p95_ms": 0.109}
求解延迟：{"count": 8, "mean_ms": 4.487, "p50_ms": 4.807, "p95_ms": 6.539}
已知 Token 用量：{"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}；
用量已知 12 条，未知 0 条。未知用量未当作 0；未估算金额。

## 逐例结果

| ID | 分类 | 预期动作 | 实际动作 | 严格匹配 | 求解状态 | 错误阶段 |
| --- | --- | --- | --- | --- | --- | --- |
| test-01 | baseline | optimize | optimize | True | optimal | — |
| test-02 | absolute_budget | optimize | optimize | True | optimal | — |
| test-03 | relative_budget | optimize | optimize | True | optimal | — |
| test-04 | relative_budget | optimize | optimize | True | optimal | — |
| test-05 | protected_and_lead_time | optimize | optimize | True | optimal | — |
| test-06 | service_budget_infeasible | optimize | optimize | True | infeasible | — |
| test-07 | exclude_with_budget | optimize | optimize | True | optimal | — |
| test-08 | multiple_demands | optimize | optimize | True | optimal | — |
| test-09 | missing_budget | clarify | clarify | True | — | — |
| test-10 | unknown_sku | clarify | clarify | True | — | — |
| test-11 | contradictory_budget | clarify | clarify | True | — | — |
| test-12 | prompt_injection | reject | reject | True | — | — |

完整输入、期望参数、实际参数、校验结果、异常和耗时均保存在同目录的 `report.json`。
dev 可用于开发；test 的首次运行报告应单独保留。看过 test 失败后进行修改的结果须另标后续回归，不能继续称为未见测试。
