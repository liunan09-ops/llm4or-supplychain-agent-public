"""Run the existing V2 Agent and export a screenshot-friendly, truthful trace.

No new tools or planning logic: this is a presentation wrapper around Agent.run.
Each invocation creates fresh synthetic SQLite data in a new output directory.
"""

import argparse
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

from rich.cells import cell_len
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from supplychain_agent.v2.agent import Agent
from supplychain_agent.v2.contracts import Request, Response
from supplychain_agent.v2.database import BusinessStore
from supplychain_agent.v2.retrieval import seed_policies
from supplychain_agent.v2.semantic_retrieval import create_retriever
from supplychain_agent.v2.trace import TraceStore

DEFAULT_MESSAGE = "先查询库存，再预算9000元，电机不能缺货"
BUSINESS_OUTCOMES = {"completed", "infeasible", "needs_clarification", "rejected"}


def export_svg(console: Console) -> str:
    """Keep exports offline and correct Rich's SVG width for wide CJK glyphs."""
    svg = console.export_svg(title="Supply Chain Decision Agent / synthetic demo", clear=False)
    svg = re.sub(r"@font-face\s*\{[^}]*\}", "", svg)
    svg = svg.replace(
        "font-family: Fira Code, monospace;",
        'font-family: Menlo, Consolas, "PingFang SC", "Microsoft YaHei", monospace;',
    )
    namespace = "http://www.w3.org/2000/svg"
    ET.register_namespace("", namespace)
    root = ET.fromstring(svg)
    for element in root.iter(f"{{{namespace}}}text"):
        value = element.text or ""
        width = element.get("textLength")
        if value and width and cell_len(value) > len(value):
            element.set("textLength", str(float(width) * cell_len(value) / len(value)))
            element.set("lengthAdjust", "spacingAndGlyphs")
    return (
        "\n".join(line.rstrip() for line in ET.tostring(root, encoding="unicode").splitlines())
        + "\n"
    )


def render(response: Response, message: str, backend: str, console: Console) -> None:
    """Display only returned facts; never synthesize a successful solver stage."""
    mode = "offline rules / no LLM" if response.mode == "demo" else "live LLM"
    console.print(
        Panel(
            Text(f"SYNTHETIC DATA | mode={mode} | retrieval={backend}"),
            title="Supply Chain Decision Agent / V2",
            border_style="cyan",
        )
    )
    console.print(Text("01  USER REQUEST", style="bold cyan"))
    console.print(Text(message))
    console.print(Text("02  INTENT / PARAMETERS", style="bold cyan"))
    if response.intent:
        params = response.intent.parameters.model_dump(exclude_none=True, exclude_defaults=True)
        console.print(Text(f"{response.intent.action} | {json.dumps(params, ensure_ascii=False)}"))
    else:
        console.print(Text("No parsed intent returned."))

    console.print(Text("03  TOOL CALLS (actual execution order)", style="bold cyan"))
    events = [event for event in response.trace if event.kind == "tool"]
    console.print(Text(" -> ".join(f"{e.name} ({e.status})" for e in events) or "Not called"))
    console.print(Text("04  RAG / POLICY CITATIONS", style="bold cyan"))
    for citation in response.citations:
        heading = citation.text.splitlines()[0]
        console.print(Text(f"{citation.id} | {citation.source} | {heading}"))
    if not response.citations:
        console.print(Text("No retrieved citations returned; see response.json for details."))

    result = response.result
    console.print(Text("05  SOLVER", style="bold cyan"))
    console.print(Text(result.status if result else "No solver result published"))
    console.print(Text("06  INDEPENDENT VALIDATOR", style="bold cyan"))
    checked = result.validation if result else None
    console.print(
        Text(f"valid={checked.valid} | checks={checked.checks}" if checked else "Not certified")
    )

    console.print(Text(f"07  FINAL RESULT: {response.status}", style="bold cyan"))
    if response.status == "completed" and result and checked and checked.valid and result.orders:
        table = Table(header_style="bold cyan", title="Verified replenishment / synthetic data")
        for label in ("SKU", "Available", "Demand", "Order", "Shortage", "Purchase cost"):
            table.add_column(label, justify="left" if label == "SKU" else "right")
        for row in result.orders:
            table.add_row(
                row.sku_id,
                str(row.initial_stock),
                str(row.demand),
                str(row.order_qty),
                str(row.shortage),
                f"{row.purchase_cost:.2f}",
            )
        console.print(table)
        console.print(
            Text(f"Purchase cost={result.purchase_cost:.2f} / Budget={result.budget:.2f}")
        )
    else:
        # Queries, infeasibility and failures must not appear as successful plans.
        console.print(Text(response.explanation))
    console.print(Text(f"Trace: {response.request_id} | LLM calls: {response.llm_calls}"))
    console.print(Text("Full facts, arguments, citations and results: response.json / trace.json"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", default=DEFAULT_MESSAGE)
    parser.add_argument("--mode", choices=("demo", "llm"), default="demo")
    parser.add_argument("--backend", choices=("lexical", "semantic", "hybrid"), default="lexical")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    request = Request(message=args.message, mode=args.mode)
    output = args.output_dir or Path(".runtime") / f"demo-v2-{uuid4().hex[:12]}"
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error("Output directory already exists; choose a new path to preserve evidence.")

    try:
        business = BusinessStore(output / "business.sqlite3")
        seed_policies(business)
        retriever = create_retriever(
            business.policies(),
            backend=args.backend,
            model_dir=args.model_dir or os.getenv("AGENT_EMBEDDING_MODEL_DIR"),
        )
        traces = TraceStore(output / "runs.sqlite3")
        response = Agent(business, retriever, traces).run(request)
    except Exception:  # noqa: BLE001 -- presentation boundary must not expose provider payloads
        # Do not print configuration values or provider exception payloads.
        print("Demo setup/run failed. Check dependencies, model files and output permissions.")
        return 2

    (output / "response.json").write_text(response.model_dump_json(indent=2) + "\n")
    (output / "trace.json").write_text(
        json.dumps(traces.get(response.request_id), ensure_ascii=False, indent=2) + "\n"
    )
    console = Console(record=True, width=100, force_terminal=True)
    render(response, args.message, args.backend, console)
    (output / "demo.svg").write_text(export_svg(console))
    (output / "demo.html").write_text(console.export_html(inline_styles=True, clear=False))
    # Keep machine-local output paths out of the shareable exports.
    console.print(Text(f"Saved display + evidence to: {output}"))
    return 0 if response.status in BUSINESS_OUTCOMES else 1


if __name__ == "__main__":
    raise SystemExit(main())
