"""Reproducible command-line demos, interactive terminal and evaluation entry points."""

import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .audit import AuditStore
from .data import demo_scenario
from .schemas import AgentRequest
from .service import run_agent


def render_response(response, console):
    color = {
        "completed": "green",
        "needs_clarification": "yellow",
        "infeasible": "yellow",
        "rejected": "red",
        "error": "red",
    }[response.status]
    console.print(
        Panel(
            response.explanation,
            title=f"[{color}]{response.status}[/{color}]",
            subtitle=f"{response.mode} / {response.model or '离线规则'} / {response.elapsed_ms:.0f} ms",
            border_style=color,
        )
    )
    if response.intent and response.intent.action == "optimize":
        params = response.intent.parameters.model_dump(exclude_none=True, exclude_defaults=True)
        console.print("[bold]已解析条件[/bold]", json.dumps(params, ensure_ascii=False))
    if response.result and response.result.orders:
        table = Table(title="补货建议 · 合成数据", header_style="bold cyan")
        for name in ["物料", "库存", "需求", "采购", "缺货", "期末库存", "采购成本"]:
            table.add_column(name, justify="left" if name == "物料" else "right")
        for line in response.result.orders:
            table.add_row(
                line.name,
                str(line.initial_stock),
                str(line.demand),
                str(line.order_qty),
                str(line.shortage),
                str(line.ending_stock),
                f"¥{line.purchase_cost:,.0f}",
            )
        console.print(table)
    for step in response.trace:
        console.print(f"  {'✓' if step.status == 'ok' else '·'} {step.name}: {step.detail}")
    console.print(f"[dim]运行编号 {response.request_id}[/dim]")


def main():
    parser = argparse.ArgumentParser(description="供应链决策 Agent · 合成数据研究项目")
    subs = parser.add_subparsers(dest="command", required=True)
    ask = subs.add_parser("ask", help="提交一条完整补货请求")
    ask.add_argument("message")
    ask.add_argument("--mode", choices=["rules", "llm"], default="rules")
    ask.add_argument("--json", action="store_true")
    ask.add_argument("--output", type=Path)
    demo = subs.add_parser("demo", help="五个场景的可复现演示")
    demo.add_argument("--mode", choices=["rules", "llm"], default="rules")
    demo.add_argument("--svg", type=Path)
    shell = subs.add_parser("chat", help="交互终端，每次输入完整条件")
    shell.add_argument("--mode", choices=["rules", "llm"], default="rules")
    subs.add_parser("scenario", help="打印合成工厂场景")
    serve = subs.add_parser("serve", help="启动本地 API，打开 /docs 交互试用")
    serve.add_argument("--port", type=int, default=8765)
    evaluate = subs.add_parser("evaluate", help="运行固定评测集")
    evaluate.add_argument("--mode", choices=["rules", "llm"], default="rules")
    evaluate.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    evaluate.add_argument("--limit", type=int)
    evaluate.add_argument("--output-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()
    console = Console(record=True, width=100)
    if args.command == "scenario":
        print(demo_scenario().model_dump_json(indent=2))
        return
    if args.command == "serve":
        import uvicorn

        uvicorn.run("supplychain_agent.api:app", host="127.0.0.1", port=args.port)
        return
    if args.command == "evaluate":
        from .evaluation import run_evaluation

        result = run_evaluation(
            mode=args.mode, split=args.split, limit=args.limit, output_dir=args.output_dir
        )
        console.print(
            Panel(
                f"模式：{args.mode} / 数据集：{args.split}\n"
                f"用例：{result['metrics']['total_cases']}\n"
                f"严格意图匹配：{result['metrics']['end_to_end_strict_intent_success']}\n"
                f"报告：{result['reports']['markdown']}",
                title="评测完成",
            )
        )
        return
    store = AuditStore(".runtime/runs.sqlite3")

    def execute(message):
        response = run_agent(AgentRequest(message=message, mode=args.mode), store=store)
        if getattr(args, "json", False):
            print(response.model_dump_json(indent=2))
        else:
            render_response(response, console)
        if getattr(args, "output", None):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(response.model_dump_json(indent=2), encoding="utf-8")
        return response

    if args.command == "ask":
        response = execute(args.message)
        if response.status == "error":
            raise SystemExit(1)
    elif args.command == "demo":
        console.print(
            Panel(
                "SUPPLYCHAIN / DECISION AGENT\n自然语言 → 约束 → 优化求解 → 独立验证",
                border_style="cyan",
            )
        )
        for message in [
            "按默认条件生成补货方案",
            "预算减少20%，生成补货方案",
            "全部物料不能缺货",
            "计划周期延长到14天，全部物料不能缺货",
            "预算15000元，计划周期延长到14天，全部物料不能缺货",
        ]:
            console.print(f"\n[bold cyan]› {message}[/bold cyan]")
            execute(message)
        if args.svg:
            args.svg.parent.mkdir(parents=True, exist_ok=True)
            console.save_svg(str(args.svg), title="SupplyChain Decision Agent")
    elif args.command == "chat":
        console.print("[bold cyan]供应链决策助手[/bold cyan] · 每次输入完整条件；输入 exit 退出")
        console.print("[dim]示例：预算9000元，电机和传感器不能缺货。每次均相对初始场景计算。[/dim]")
        while True:
            try:
                message = console.input("\n[bold cyan]你 › [/bold cyan]").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if message.lower() in {"exit", "quit", "退出"}:
                break
            if message:
                execute(message)


if __name__ == "__main__":
    main()
