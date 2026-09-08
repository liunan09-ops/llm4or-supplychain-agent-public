"""Explicit bounded state machine; native tools in LLM mode, documented DSL in demo."""

import json
import re
import time
from uuid import uuid4

from ..language import ModelError, _reject_reason, _resolve_skus, parse_rules
from ..optimizer import resolve_scenario
from ..schemas import PlanParameters
from .contracts import Event, Intent, Limits, Request, Response, ToolCall
from .database import DataError
from .model import TOOL_PROMPT, AnswerSelection, V2ModelClient
from .tools import ToolContext, ToolError, execute


def numeric_parameters_grounded(message, parameters):
    """Conservative execution gate: changed scalars need explicit Arabic numerals.

    This is a guard, not claimed as LLM intent accuracy. Natural-language number
    words or implied numeric changes require clarification in V2.
    """
    numbers = {abs(float(n)) for n in re.findall(r"[-+]?\d+(?:\.\d+)?", message)}
    required = [parameters.budget, parameters.budget_change_pct, parameters.horizon_days]
    if parameters.min_service_level is not None:
        required.append(parameters.min_service_level * 100)
    required.extend(d.demand for d in parameters.demand_updates)
    return all(
        any(abs(abs(value) - n) < 1e-8 for n in numbers) for value in required if value is not None
    )


def demo_intent(message, snapshot):
    reject = _reject_reason(message)
    if reject:
        return Intent(action="reject", reason=reject)
    for prefix, action in (
        ("查询库存", "inventory"),
        ("查询供应商", "supplier"),
        ("查询订单", "orders"),
    ):
        match = re.fullmatch(re.escape(prefix) + r"(?:[：: ]\s*(.+))?", message.strip())
        if match:
            ids = _resolve_skus(match[1], snapshot.scenario()) if match[1] else []
            if ids is None:
                return Intent(
                    action="clarify", questions=["请提供数据库中存在的 SKU 编号或物料名称。"]
                )
            return Intent(action=action, sku_ids=ids)
    match = re.fullmatch(r"查询政策[：:]\s*(.+)", message.strip())
    if match:
        return Intent(action="policy", policy_query=match[1])
    match = re.fullmatch(r"先查询库存[，,]再(.+)", message.strip())
    parsed = parse_rules(match[1] if match else message, snapshot.scenario())
    payload = parsed.model_dump()
    if match and parsed.action == "optimize":
        payload["action"] = "query_then_optimize"
    return Intent.model_validate(payload)


def ready(intent, ctx):
    expected = set(intent.sku_ids) or ctx.snapshot.ids
    if intent.action in {"optimize", "query_then_optimize"}:
        return ctx.verified or (ctx.proposal is not None and ctx.proposal.status == "infeasible")
    if intent.action == "inventory":
        return expected.issubset(ctx.inventory_seen)
    if intent.action == "supplier":
        return expected.issubset(ctx.suppliers_seen)
    if intent.action == "orders":
        return "purchase_orders" in ctx.facts and expected.issubset(ctx.orders_seen)
    return bool(ctx.citations) if intent.action == "policy" else False


def demo_step(intent, ctx):
    if ready(intent, ctx):
        return None
    if intent.action in {"inventory", "supplier", "orders"}:
        name = {
            "inventory": "inventory_query",
            "supplier": "supplier_query",
            "orders": "order_query",
        }[intent.action]
        args = {"sku_ids": intent.sku_ids}
    elif intent.action == "policy":
        name, args = "policy_retrieval", {"query": intent.policy_query}
    elif ctx.inventory_seen != ctx.snapshot.ids:
        name, args = "inventory_query", {"sku_ids": []}
    elif ctx.suppliers_seen != ctx.snapshot.ids:
        name, args = "supplier_query", {"sku_ids": []}
    elif not ctx.citations:
        name, args = "policy_retrieval", {"query": "采购预算 MOQ 交期 服务水平"}
    elif ctx.proposal is None:
        name, args = "replenishment_optimizer", {"parameters": intent.parameters.model_dump()}
    else:
        name, args = "solution_validator", {"plan_id": ctx.plan_id}
    return ToolCall(id=uuid4().hex, name=name, arguments=args)


def available_tools(intent, ctx):
    """Expose valid next actions; LLM chooses read order, batching and arguments."""
    if ready(intent, ctx):
        return {"finish_request"}
    query_tools = {
        "inventory": "inventory_query",
        "supplier": "supplier_query",
        "orders": "order_query",
        "policy": "policy_retrieval",
    }
    if intent.action in query_tools:
        return {query_tools[intent.action]}
    missing = set()
    if ctx.inventory_seen != ctx.snapshot.ids:
        missing.add("inventory_query")
    if ctx.suppliers_seen != ctx.snapshot.ids:
        missing.add("supplier_query")
    if not ctx.citations:
        missing.add("policy_retrieval")
    if missing:
        return missing
    return {"solution_validator" if ctx.proposal is not None else "replenishment_optimizer"}


def evidence_catalog(intent, ctx):
    catalog = {}
    for row in ctx.facts.get("inventory", []):
        key = "inventory:" + row["sku_id"]
        catalog[key] = {
            "text": f"{row['sku_id']}：现货 {row['on_hand']}，在途 {row['in_transit']}，{row['horizon_days']} 天窗口内可用库存 {row['available_in_horizon']}，原始需求 {row['demand']}。[SQLite snapshot {ctx.snapshot.snapshot_id[:12]}]",
            "required": intent.action in {"inventory", "query_then_optimize"},
        }
    for row in ctx.facts.get("suppliers", []):
        catalog["supplier:" + row["sku_id"]] = {
            "text": f"{row['sku_id']}：供应商 {row['supplier_id']}（{row['status']}），单价 {row['unit_cost']}，MOQ {row['min_order_qty']}，上限 {row['max_order_qty']}，交期 {row['lead_time_days']} 天。[SQLite snapshot {ctx.snapshot.snapshot_id[:12]}]",
            "required": intent.action == "supplier",
        }
    if "purchase_orders" in ctx.facts:
        rows = ctx.facts["purchase_orders"]
        catalog["orders"] = {
            "text": "采购订单查询："
            + json.dumps(rows, ensure_ascii=False)
            + " [SQLite purchase_orders]",
            "required": intent.action == "orders",
        }
    for index, cite in enumerate(ctx.citations.values()):
        catalog[cite.id] = {
            "text": f"[{cite.id} · {cite.source}] {cite.text}",
            "required": intent.action == "policy" and index == 0,
        }
    if ctx.verified:
        r = ctx.proposal
        catalog["plan"] = {
            "text": f"方案状态 {r.status}；采购成本 {r.purchase_cost:.2f} / 预算 {r.budget:.2f}；总目标成本 {r.total_cost:.2f}；总体满足率 {r.fill_rate:.2%}。独立校验通过。",
            "required": True,
        }
        catalog["orders:plan"] = {
            "text": "建议采购数量："
            + "；".join(f"{r.sku_id} {r.order_qty}" for r in ctx.proposal.orders)
            + "。仅建议，未下单。",
            "required": True,
        }
    elif ctx.proposal is not None and ctx.proposal.status == "infeasible":
        catalog["infeasible"] = {
            "text": "当前条件不可行，未放宽约束。" + "；".join(ctx.proposal.diagnostics),
            "required": True,
        }
    return catalog


def render_answer(selection, catalog, ctx):
    ids = selection.evidence_ids
    if len(ids) != len(set(ids)) or any(key not in catalog for key in ids):
        raise ModelError("unknown_or_duplicate_answer_evidence")
    if not {key for key, value in catalog.items() if value["required"]}.issubset(ids):
        raise ModelError("required_answer_evidence_missing")
    if ctx.citations and not set(ids).intersection(ctx.citations):
        raise ModelError("answer_policy_citation_missing")
    return "\n".join(catalog[key]["text"] for key in ids)


class Agent:
    def __init__(
        self,
        business,
        retriever,
        traces,
        *,
        model_factory=V2ModelClient.from_env,
        limits=None,
        tool_executor=execute,
        solver=None,
        validator=None,
    ):
        self.business, self.retriever, self.traces = business, retriever, traces
        self.model_factory, self.limits = model_factory, limits or Limits()
        self.tool_executor, self.solver, self.validator = tool_executor, solver, validator

    def run(self, request: Request, *, structured_parameters: PlanParameters | None = None):
        started = time.perf_counter()
        request_id = uuid4().hex
        events = []
        model = None
        ctx = None
        intent = None
        tool_calls = 0
        replans = 0
        status, explanation = "tool_failure", "未能完成请求。"
        self.traces.start(request_id, request)

        def emit(kind, name, state, data=None, elapsed=0):
            event = Event(
                sequence=len(events) + 1,
                kind=kind,
                name=name,
                status=state,
                data=json.loads(json.dumps(data or {}, ensure_ascii=False)),
                elapsed_ms=round(elapsed, 3),
            )
            self.traces.event(request_id, event)
            events.append(event)

        def budget():
            remaining = self.limits.total_seconds - (time.perf_counter() - started)
            if remaining <= 0:
                raise ToolError("request_timeout")
            return remaining

        def model_call(name, fn, *args):
            nonlocal replans
            for repair in range(2):
                if model.calls >= self.limits.max_model_calls:
                    raise ToolError("max_model_calls")
                model.remaining_seconds = budget()
                ok = False
                try:
                    result = fn(*args)
                    ok = True
                    return result
                except ModelError as exc:
                    repairable = str(exc).startswith(
                        (
                            "malformed_",
                            "required_answer_",
                            "answer_policy_",
                            "unknown_or_duplicate_answer_",
                        )
                    )
                    if (
                        repair == 1
                        or name == "tool_selection"
                        or not repairable
                        or replans >= self.limits.max_replans
                    ):
                        raise
                    replans += 1
                    model.repair_feedback = str(exc)
                    emit(
                        "state",
                        "repair_model_output",
                        "running",
                        {"replans": replans, "error": str(exc)},
                    )
                finally:
                    emit(
                        "llm",
                        name,
                        "ok" if ok else "error",
                        model.last_record,
                        model.last_record.get("elapsed_ms", 0),
                    )
                    if ok or repair == 1:
                        model.repair_feedback = ""

        try:
            emit("state", "load_snapshot", "running")
            snapshot = self.business.snapshot(request.scenario_id)
            self.traces.snapshot(request_id, snapshot)
            effective_request = request
            if request.previous_request_id:
                # A clarification continuation supplies a complete revised request;
                # do not silently merge conflicting old and new constraints.
                previous = self.traces.get(request.previous_request_id)
                if (
                    not previous
                    or not previous["response"]
                    or previous["response"]["status"] != "needs_clarification"
                ):
                    raise ToolError("invalid_clarification_parent")
                emit(
                    "state",
                    "clarification_continuation",
                    "running",
                    {
                        "previous_request_id": request.previous_request_id,
                        "semantics": "complete_replacement",
                    },
                )
            emit("state", "detect_intent", "running")
            if structured_parameters is not None:
                if request.mode != "demo":
                    raise ToolError("structured_request_must_be_demo")
                intent = Intent(action="optimize", parameters=structured_parameters)
            elif _reject_reason(request.message):
                intent = Intent(action="reject", reason=_reject_reason(request.message))
            elif request.mode == "demo":
                intent = demo_intent(request.message, snapshot)
            else:
                model = self.model_factory()
                intent = model_call("intent", model.intent, effective_request, snapshot)
                if not numeric_parameters_grounded(request.message, intent.parameters):
                    emit(
                        "state",
                        "numeric_grounding_guard",
                        "clarify",
                        {"parsed_intent": intent.model_dump()},
                    )
                    intent = Intent(
                        action="clarify",
                        questions=[
                            "执行参数需要原请求中的明确数字。请用阿拉伯数字给出预算、百分比、天数或需求量，并提交完整条件。"
                        ],
                    )
            if not set(intent.sku_ids).issubset(snapshot.ids):
                intent = Intent(action="clarify", questions=["请使用已有的 SKU 编号。"])
            try:
                resolve_scenario(snapshot.scenario(intent.parameters), intent.parameters)
            except ValueError:
                intent = Intent(
                    action="clarify",
                    questions=["参数或物料不适用于当前场景，请提供完整的有效条件。"],
                )
            emit("intent", "locked_intent", intent.action, intent.model_dump())
            budget()
            if intent.action == "clarify":
                status, explanation = (
                    "needs_clarification",
                    "；".join(intent.questions) + " 请在下一次请求中提交完整条件。",
                )
            elif intent.action == "reject":
                status, explanation = "rejected", intent.reason or "请求超出只读补货建议范围。"
            else:
                ctx = ToolContext(
                    snapshot,
                    parameters=intent.parameters,
                    allow_optimization=intent.action in {"optimize", "query_then_optimize"},
                    retriever=self.retriever,
                    tool_seconds=self.limits.tool_seconds,
                )
                if self.solver is not None:
                    ctx.solver = self.solver
                if self.validator is not None:
                    ctx.validator = self.validator
                messages = [
                    {"role": "system", "content": TOOL_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "request": request.message,
                                "locked_intent": intent.model_dump(),
                                "scenario_defaults": snapshot.config,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ]
                seen_call_ids = set()
                pending_calls = []
                while True:
                    budget()
                    emit("state", "choose_tool", "running")
                    if model:
                        if not pending_calls:
                            model.available_tools = available_tools(intent, ctx)
                            batch, assistant = model_call("tool_selection", model.step, messages)
                            messages.append(assistant)
                            pending_calls = batch or []
                        call = pending_calls.pop(0) if pending_calls else None
                    else:
                        call = demo_step(intent, ctx)
                    if call is None:
                        if ready(intent, ctx):
                            break
                        replans += 1
                        emit("state", "replan", "premature_finish", {"replans": replans})
                        if replans > self.limits.max_replans:
                            raise ToolError("max_replans")
                        messages.append(
                            {
                                "role": "user",
                                "content": "Required evidence is missing. Complete the locked task with tools before finishing.",
                            }
                        )
                        continue
                    if call.id in seen_call_ids:
                        raise ToolError("duplicate_tool_call_id")
                    seen_call_ids.add(call.id)
                    output = None
                    for attempt in range(self.limits.max_tool_retries + 1):
                        budget()
                        if tool_calls >= self.limits.max_tool_calls:
                            raise ToolError("max_tool_calls")
                        tool_calls += 1
                        ctx.tool_seconds = min(self.limits.tool_seconds, budget())
                        tool_started = time.perf_counter()
                        try:
                            if model and call.name not in model.available_tools:
                                raise ToolError("tool_not_available_in_state")
                            output = self.tool_executor(call.name, call.arguments, ctx)
                            elapsed = (time.perf_counter() - tool_started) * 1000
                            emit(
                                "tool",
                                call.name,
                                "ok",
                                {
                                    "call_id": call.id,
                                    "attempt": attempt + 1,
                                    "arguments": call.arguments,
                                    "result": output,
                                },
                                elapsed,
                            )
                            if call.name == "policy_retrieval":
                                emit("retrieval", "policy_evidence", "ok", output)
                            if elapsed > ctx.tool_seconds * 1000:
                                raise ToolError("tool_timeout")
                            break
                        except ToolError as exc:
                            emit(
                                "tool",
                                call.name,
                                "error",
                                {
                                    "call_id": call.id,
                                    "attempt": attempt + 1,
                                    "arguments": call.arguments,
                                    "error": exc.code,
                                },
                                (time.perf_counter() - tool_started) * 1000,
                            )
                            if exc.retryable and attempt < self.limits.max_tool_retries:
                                emit("state", "retry_tool", "running", {"tool": call.name})
                                continue
                            if (
                                exc.code in {"validator_failure", "solver_failure", "tool_timeout"}
                                or call.name == "solution_validator"
                            ):
                                raise
                            if not exc.retryable and exc.code in {
                                "invalid_tool_arguments",
                                "unknown_tool",
                                "tool_not_available_in_state",
                                "parameters_must_match_locked_intent",
                                "query_all_inventory_and_suppliers_before_optimization",
                                "retrieve_policy_before_optimization",
                                "unknown_sku",
                            }:
                                replans += 1
                                emit("state", "replan", "tool_error", {"replans": replans})
                                if replans > self.limits.max_replans:
                                    raise ToolError("max_replans") from None
                                output = {
                                    "error": exc.code,
                                    "locked_parameters": intent.parameters.model_dump(),
                                }
                                break
                            raise
                    if model:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": json.dumps(output, ensure_ascii=False),
                            }
                        )
                budget()
                emit("state", "explain_from_evidence", "running")
                catalog = evidence_catalog(intent, ctx)

                def checked_selection(catalog):
                    selection = model.explain(catalog)
                    render_answer(selection, catalog, ctx)
                    return selection

                selection = (
                    model_call("answer_selection", checked_selection, catalog)
                    if model
                    else AnswerSelection(evidence_ids=list(catalog))
                )
                explanation = render_answer(selection, catalog, ctx)
                budget()
                emit(
                    "state",
                    "answer_evidence",
                    "ok",
                    {"selection": selection.model_dump(), "catalog": catalog},
                )
                status = (
                    "infeasible"
                    if ctx.proposal is not None and ctx.proposal.status == "infeasible"
                    else "completed"
                )
        except ModelError as exc:
            status, explanation = "llm_failure", str(exc)
            emit("error", "model", status, {"error": str(exc)})
        except (ToolError, DataError) as exc:
            code = str(exc)
            status = (
                "validator_failure"
                if code == "validator_failure"
                else (
                    "limit_exceeded"
                    if code.startswith("max_") or code in {"request_timeout", "tool_timeout"}
                    else "tool_failure"
                )
            )
            explanation = "执行终止：" + code + "。未发布未经确认的方案。"
            emit("error", "execution", status, {"error": code})
        except Exception:  # noqa: BLE001 -- fail closed and persist a public-safe terminal outcome
            status, explanation = (
                "tool_failure",
                "执行遇到内部错误；请使用 request_id 检查本地记录。",
            )
            emit("error", "execution", status, {"error": "internal_error"})
        emit("final", "outcome", status)
        response = Response(
            request_id=request_id,
            status=status,
            mode=request.mode,
            model=model.model if model else None,
            intent=intent,
            explanation=explanation,
            result=ctx.proposal
            if ctx
            and ctx.proposal is not None
            and status in {"completed", "infeasible"}
            and (ctx.verified or ctx.proposal.status == "infeasible")
            else None,
            facts=ctx.facts if ctx else {},
            citations=list(ctx.citations.values()) if ctx else [],
            trace=events,
            tool_calls=tool_calls,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
            snapshot_id=ctx.snapshot.snapshot_id
            if ctx
            else (snapshot.snapshot_id if "snapshot" in locals() else None),
        )
        if model:
            response.usage, response.usage_known = model.usage, model.usage_known
            response.llm_calls, response.http_attempts = model.calls, model.attempts
        self.traces.finish(response)
        return response
