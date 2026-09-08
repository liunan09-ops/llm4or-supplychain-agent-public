"""Aggregate actual saved runs; never invent metrics or rerun a model."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "evaluation"


def rate(metric):
    return (
        f"{metric['passed']}/{metric['total']} ({metric['rate']:.2%})"
        if metric["total"]
        else "N/A (0 cases)"
    )


def main():
    names = [
        "dev_demo_final",
        "dev_llm_final",
        "heldout_demo",
        "heldout_llm",
        "retrieval_dev",
        "retrieval_heldout",
    ]
    data = {name: json.loads((EVAL / "runs_v2" / (name + ".json")).read_text()) for name in names}
    aggregate = {
        "provenance": "synthetic / demo data; AI-assisted development and dataset authoring",
        "protocol": "PROTOCOL_V2.md",
        "runs": {
            name: {
                "path": "runs_v2/" + name + ".json",
                "sha256": hashlib.sha256(
                    (EVAL / "runs_v2" / (name + ".json")).read_bytes()
                ).hexdigest(),
                "kind": run["kind"],
                "metrics": run["metrics"],
                "dataset_sha256": run["dataset_sha256"],
                "source_sha256": run["metadata"]["source_sha256"],
                "failed_case_ids": [
                    row["case"]["id"]
                    for row in run["cases"]
                    if "score" in row and not row["score"]["end_to_end_success"]
                ],
            }
            for name, run in data.items()
        },
    }
    aggregate["development_debug_runs"] = [
        "runs_v2/dev_llm_initial.json",
        "runs_v2/dev_llm_v2.json",
        "runs_v2/dev_llm_v3.json",
    ]
    all_live = [
        json.loads(path.read_text())
        for path in (EVAL / "runs_v2").glob("*.json")
        if "llm" in path.name
    ]
    aggregate["all_saved_live_attempts"] = {
        "runs": len(all_live),
        "llm_calls": sum(r["metrics"]["llm_calls"] for r in all_live),
        "reported_tokens": sum(
            r["metrics"]["known_usage_tokens"]["total_tokens"] for r in all_live
        ),
        "estimated_cost": None,
        "note": "Includes failed development attempts; debug protocols/metrics differ. Not a single benchmark.",
    }
    (EVAL / "results_v2.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n"
    )
    dev, held = data["dev_llm_final"]["metrics"], data["heldout_llm"]["metrics"]
    labels = {
        "intent_correct": "系统意图（含防护）",
        "raw_model_intent_correct": "模型意图（仅实际调用子集）",
        "tool_selection_correct": "工具集合完全匹配",
        "tool_arguments_correct": "全部尝试参数正确",
        "retrieval_hit": "Agent 检索相关文档命中",
        "constraint_pass": "已发布方案约束校验",
        "end_to_end_success": "端到端任务成功",
        "clarification_correct": "澄清正确",
        "refusal_correct": "拒绝正确",
    }
    lines = [
        "# V2 评测报告",
        "",
        "本报告由 `scripts/report_v2.py` 读取真实运行 JSON 生成。所有数据为 **synthetic / demo data**；没有企业部署、节省金额或招聘结果指标。",
        "",
        "## Deterministic tests 与 Demo",
        "",
        "Pytest 的数量和结果见 `evidence/test_summary.json`；它包含确定性工具、数据库、solver、validator、HTTP MockTransport、异常和 API 集成测试，不能当成 LLM 准确率。",
        "",
        f"Demo 开发集端到端 {rate(data['dev_demo_final']['metrics']['end_to_end_success'])}；同一自然语言留出集 {rate(data['heldout_demo']['metrics']['end_to_end_success'])}。Demo 只支持文档化 DSL，因此自由改写常返回澄清。",
        "",
        "## 真实 LLM 与 held-out evaluation",
        "",
        "模型请求配置为 `deepseek-v4-flash`，温度 0、thinking disabled，单次响应上限 1200 tokens。逐调用 provider_model、usage 和错误保存在原始 JSON。",
        "",
        "| 指标 | 开发集 | 留出集 |",
        "| --- | --- | --- |",
    ]
    for name, label in labels.items():
        lines.append(f"| {label} | {rate(dev[name])} | {rate(held[name])} |")
    lines.extend(
        [
            "",
            "工具集合匹配率受状态机可选工具掩码约束；不能解释为完全开放工具库中的模型路由水平。端到端指标允许安全恢复，参数指标则对曾出现错误参数的请求记错。",
            "",
            "| 成本与性能记录 | 开发集 | 留出集 |",
            "| --- | --- | --- |",
            f"| 延迟 p50 / p95（秒） | {dev['latency_ms']['p50'] / 1000:.3f} / {dev['latency_ms']['p95'] / 1000:.3f} | {held['latency_ms']['p50'] / 1000:.3f} / {held['latency_ms']['p95'] / 1000:.3f} |",
            f"| LLM 调用 / HTTP 尝试 | {dev['llm_calls']} / {dev['http_attempts']} | {held['llm_calls']} / {held['http_attempts']} |",
            f"| API 返回总 tokens | {dev['known_usage_tokens']['total_tokens']} | {held['known_usage_tokens']['total_tokens']} |",
            f"| usage 全部已知 | {dev['all_usage_known']} | {held['all_usage_known']} |",
            "| 金额成本 | 未计算 | 未计算 |",
            "",
            "没有可靠的模型版本及缓存命中费率表，金额记 null。延迟是本机顺序请求墙钟时间，含 API、SQLite 和重试；不是并发压测。保护规则直接拒绝的请求没有 LLM 调用。",
            "",
            "## 留出失败案例（未修改评分或补规则）",
            "",
            "- `v2-test-02`：求解及校验执行后，模型最终解释缺少政策 citation；修复额度耗尽，系统返回 llm_failure，未发布该方案。",
            "- `v2-test-17`：用户显式指定 7 天，模型因其等于默认值而省略 horizon_days；不可行判断本身正确，但按预先冻结的显式参数口径判错。此项不表示模型把交期改成了 7 天。",
            "",
            "## 独立 retrieval",
            "",
            "Markdown → 标题分块 → 中文双字/英文词 TF-IDF embedding → FAISS IndexFlatIP → source/citation。没有预训练语义 embedding、reranker 或在线向量服务。",
            "",
            "| 集合 | Hit@1 | Hit@3 | 文档 Recall@3 | MRR@3 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for name in ("retrieval_dev", "retrieval_heldout"):
        m = data[name]["metrics"]
        lines.append(
            f"| {name} | {rate(m['hit_at_1'])} | {rate(m['hit_at_3'])} | {m['recall_at_3']:.3f} | {m['mrr_at_3']:.3f} |"
        )
    lines.extend(
        [
            "",
            "检索留出集包含中文改写和英文问题；词法匹配仍有漏检。原文命中率不能替代答案正确率或业务合规证明。",
            "",
            "## 隔离与复现边界",
            "",
            "源码在创建 V2 留出集前冻结，见 `evidence/pre_heldout_freeze.json`。留出运行的源码 hash 与冻结记录相同，运行中没有改源码。ID 和请求文本无开发/留出重叠，结构化 solver 验证了优化标注，见 `evidence/heldout_label_validation.json`。",
            "",
            "V2 留出样本由同一 AI 辅助开发过程编写，属于开发后保留的合成样本，不是独立第三方盲测；样本很小，不代表企业数据泛化能力。原 V1 留出集已读过，只能称回归。",
            "",
            "首轮及中间开发失败日志保存在 `runs_v2/dev_llm_initial.json`、`dev_llm_v2.json`、`dev_llm_v3.json`。其协议与评分实现不同，只用于问题追踪；简历数字使用最终冻结运行。",
            "",
            "复现命令与所有分母、故障注入和评分定义见 [PROTOCOL_V2.md](PROTOCOL_V2.md)。汇总结果和逐例证据索引见 [results_v2.json](results_v2.json)。",
            "",
        ]
    )
    (EVAL / "report_v2.md").write_text("\n".join(lines))
    print(
        json.dumps(
            {
                "heldout_success": held["end_to_end_success"],
                "outputs": ["evaluation/results_v2.json", "evaluation/report_v2.md"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
