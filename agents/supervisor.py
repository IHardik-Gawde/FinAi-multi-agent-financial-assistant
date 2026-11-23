import json
import re
import time
from typing import Any

from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, END

from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeElapsedColumn,
)

from agents.states import FinanceAgentState
from agents.finance_agent import finance_node_result
from agents.research_agent import research_agent

from agents.editor_agent import editor_agent


# The Supervisor uses the LLM to classify the complete user request.
# Keep the existing model configuration unchanged.
llm = ChatOllama(
    model="qwen3:1.7b",
    temperature=0,
    reasoning=False,
    format="json",
    num_ctx=2048,
    num_predict=200,
    keep_alive="30m",
)

progress = Progress(
    SpinnerColumn(),
    TextColumn("[bold cyan]{task.description}"),
    BarColumn(),
    TextColumn("[dim]{task.percentage:>3.0f}%"),
    TimeElapsedColumn(),
    transient=False,
)

task_ids: dict[str, int] = {}

VALID_ROUTES = {"finance", "research", "both"}
MAX_DEBUG_CHARS = 12000


SUPERVISOR_PROMPT = """You are the routing Supervisor for an AI Finance Employee.
Read the COMPLETE user request before deciding. Do not split the request into
comma-separated fragments or route individual company names separately.
Return exactly one valid JSON object.

FINANCE:
Use Finance for financial calculations, comparisons, rankings, and conclusions
derived from financial metrics. This includes comparing multiple companies by
revenue, expenses, profit, operating difference, margins, growth, ratios, or
other financial measures. If the user asks which company is more profitable,
Finance must compare the relevant profitability measures. Include EVERY company
and metric named in the original request in finance_task.

RESEARCH:
Use Research when the user wants information extracted or explained from
uploaded documents without asking for a financial calculation or comparison.
Examples include listing PDFs, finding what a report says, retrieving a single
reported figure, invoice details/status, or qualitative explanations in reports.

BOTH:
Use both only when the request contains two distinct deliverables:
(1) a financial calculation/comparison for Finance, and
(2) a separate document lookup or qualitative explanation for Research.
Do not use Research merely because financial source documents are involved.
Finance handles financial calculations using the finance data available to it.

DECISION GUIDANCE:
- Comparing or ranking companies by financial figures is FINANCE, even when
  the user says "total revenue" or names several companies.
- Asking for one figure exactly as reported, without calculation/comparison,
  is RESEARCH.
- Asking which company is more profitable requires FINANCE.
- Use BOTH only for genuinely separate finance and document-research tasks.
- Preserve all company names, requested metrics, time periods, and conditions
  in the relevant task. Never omit entities from a multi-company request.
- Do not invent additional tasks.
- For an unambiguous request, pass the complete request to the selected agent.
- Set the task for every unselected agent to null.

EXAMPLES:
User: "Compare CedarPeak, Redwood and Greenline by total revenue and tell me
which is more profitable."
Return: {"route":"finance","finance_task":"Compare CedarPeak, Redwood and Greenline by total revenue and determine which is more profitable. Include all three companies.","research_task":null,"route_reason":"This compares financial metrics and profitability."}

User: "How much revenue did Redwood report in February?"
Return: {"route":"research","finance_task":null,"research_task":"Find Redwood's February revenue as stated in the uploaded report.","route_reason":"This is a single reported-figure lookup."}

User: "Calculate ABC's outstanding amount and check the report for an explanation
of why the invoices are unpaid."
Return: {"route":"both","finance_task":"Calculate ABC's outstanding amount.","research_task":"Check the report for an explanation of why the invoices are unpaid.","route_reason":"This has a calculation and a separate document-explanation task."}

User: "List all PDFs in the vector store."
Return: {"route":"research","finance_task":null,"research_task":"List all uploaded PDFs in the vector store.","route_reason":"This is a document inventory request."}

Output keys: route ("finance"|"research"|"both"), finance_task, research_task,
route_reason (short). Return JSON only.
"""


def _debug(event: str, **details: Any) -> None:
    """Print structured workflow diagnostics without flooding the terminal."""
    payload = json.dumps(details, ensure_ascii=False, default=str, sort_keys=True)
    if len(payload) > MAX_DEBUG_CHARS:
        payload = payload[:MAX_DEBUG_CHARS] + " ...[debug output truncated]"
    print(f"[SUPERVISOR_DEBUG] {event} {payload}", flush=True)


def _debug_result(event: str, result: Any) -> None:
    """Print an agent's actual returned value, with a safe terminal limit."""
    serialized = json.dumps(result, ensure_ascii=False, default=str, indent=2)
    truncated = len(serialized) > MAX_DEBUG_CHARS
    _debug(
        event,
        result=serialized[:MAX_DEBUG_CHARS],
        truncated=truncated,
        original_length=len(serialized),
    )


def reset_progress():
    """Clear tasks from the previous workflow execution."""
    global task_ids
    for task in list(progress.tasks):
        progress.remove_task(task.id)
    task_ids = {}


def create_task(agent_name):
    """Create a progress task for an agent."""
    task_id = progress.add_task(
        f"[cyan]{agent_name} running...",
        total=1,
    )
    task_ids[agent_name] = task_id
    return task_id


def run_agent(agent_name, function, task_id):
    """Execute an agent and update its progress."""
    start_time = time.perf_counter()
    try:
        result = function()
        elapsed = time.perf_counter() - start_time
        progress.update(
            task_id,
            completed=1,
            description=f"[green]✓ {agent_name} completed ({elapsed:.2f}s)",
        )
        _debug(
            "AGENT_EXECUTION_COMPLETE",
            agent=agent_name,
            elapsed_seconds=round(elapsed, 3),
        )
        return result
    except Exception as exc:
        progress.update(
            task_id,
            description=f"[red]✗ {agent_name} failed",
        )
        _debug(
            "AGENT_EXECUTION_FAILED",
            agent=agent_name,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise


def _parse_supervisor_decision(response_text: str) -> dict:
    """Extract and validate the JSON routing decision from the LLM response."""
    cleaned = re.sub(
        r"<think>.*?</think>", "", str(response_text), flags=re.DOTALL
    ).strip()
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE
    ).strip()

    decoder = json.JSONDecoder()
    decision = None
    for position, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(cleaned[position:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            decision = candidate
            break

    if decision is None:
        raise ValueError("Supervisor response did not contain a valid JSON object.")

    route = str(decision.get("route", "")).strip().lower()
    if route not in VALID_ROUTES:
        raise ValueError(f"Invalid Supervisor route: {route!r}")

    finance_task = decision.get("finance_task")
    research_task = decision.get("research_task")

    if route in {"finance", "both"}:
        if not isinstance(finance_task, str) or not finance_task.strip():
            raise ValueError(
                "Supervisor selected Finance but did not provide finance_task."
            )
        finance_task = finance_task.strip()
    else:
        finance_task = None

    if route in {"research", "both"}:
        if not isinstance(research_task, str) or not research_task.strip():
            raise ValueError(
                "Supervisor selected Research but did not provide research_task."
            )
        research_task = research_task.strip()
    else:
        research_task = None

    route_reason = decision.get("route_reason")
    if not isinstance(route_reason, str) or not route_reason.strip():
        route_reason = "Model routing decision."

    return {
        "route": route,
        "route_reason": route_reason.strip(),
        "finance_task": finance_task,
        "research_task": research_task,
    }


def _normalize_company_suffixes(text: str) -> str:
    """Speech says 'Private Limited' / 'Limited'; documents print 'Pvt. Ltd' / 'Ltd'.
    Normalise so downstream exact company-name matching succeeds."""
    text = re.sub(r"\bprivate\s+limited\b", "Pvt. Ltd", text, flags=re.I)
    text = re.sub(r"\bpvt\.?\s+limited\b", "Pvt. Ltd", text, flags=re.I)
    text = re.sub(
        r"\blimited\b(?!\s+(?:liability|time|edition|number|access|resources|budget|data))",
        "Ltd",
        text,
        flags=re.I,
    )
    return text


def _classify_user_request(user_query: str) -> dict:
    """Use the LLM to route the complete request without hardcoded rules."""
    if not isinstance(user_query, str) or not user_query.strip():
        raise ValueError("Cannot route an empty user request.")

    source = "llm"
    try:
        response = llm.invoke(
            [
                ("system", SUPERVISOR_PROMPT),
                ("human", f"COMPLETE USER REQUEST:\\n{user_query.strip()}"),
            ]
        )
        decision = _parse_supervisor_decision(response.content)
    except Exception as exc:  # small models occasionally emit bad JSON
        _debug("LLM_ROUTING_FAILED_DEFAULTING_TO_RESEARCH", error=str(exc))
        source = "fallback"
        decision = {
            "route": "research",
            "route_reason": "Routing model failed; research is the safe read-only default.",
            "finance_task": None,
            "research_task": f"Answer from the uploaded documents only: {user_query.strip()}",
        }

    selected_agents = (
        ["finance", "research"] if decision["route"] == "both" else [decision["route"]]
    )
    decision["next_agent"] = selected_agents
    _debug(
        "ROUTING_DECISION",
        source=source,
        user_query=user_query.strip(),
        route=decision["route"],
        route_reason=decision["route_reason"],
        selected_agents=selected_agents,
        finance_task=decision["finance_task"],
        research_task=decision["research_task"],
    )
    return decision


def _build_specialist_input(
    user_query: str, specialist_task: str, specialist: str
) -> str:
    """Preserve the original request and append the Supervisor's specialist task."""
    return (
        "ORIGINAL USER REQUEST:\n"
        f"{user_query.strip()}\n\n"
        f"SUPERVISOR ASSIGNMENT FOR {specialist.upper()} AGENT:\n"
        f"{specialist_task.strip()}\n\n"
        "Complete only the contribution needed to satisfy the original user request. "
        "Treat this assignment as scope guidance, not as evidence or a statement that "
        "any suggested finding exists. The original user request is authoritative. "
        "Do not answer unrelated questions or assume facts that are not supported by your sources."
    )


def supervisor_node(state: FinanceAgentState):
    reset_progress()
    progress.start()
    supervisor_task_id = create_task("Supervisor")

    try:
        user_query = _normalize_company_suffixes(state["user_query"])
        decision = run_agent(
            "Supervisor",
            lambda: _classify_user_request(user_query),
            supervisor_task_id,
        )

        selected_agents = decision["next_agent"]
        if "finance" in selected_agents:
            create_task("Finance Agent")
        if "research" in selected_agents:
            create_task("Research Agent")
        create_task("Editor Agent")

        _debug(
            "TASKS_DISPATCHED",
            selected_agents=selected_agents,
            finance_task=decision["finance_task"],
            research_task=decision["research_task"],
        )

        return {
            "user_query": user_query,
            "next_agent": selected_agents,
            "finance_task": decision["finance_task"],
            "research_task": decision["research_task"],
        }
    except Exception:
        progress.stop()
        raise


def route_to_agent(state: FinanceAgentState) -> list[str]:
    """Route only to agents explicitly selected by the Supervisor."""
    selected = state.get("next_agent")
    if not selected:
        raise ValueError(
            "Supervisor did not select an agent. Refusing to default to Finance."
        )

    invalid = set(selected) - {"finance", "research"}
    if invalid:
        raise ValueError(f"Supervisor selected invalid agent(s): {sorted(invalid)}")
    return selected


def finance_node(state: FinanceAgentState):
    finance_task = state.get("finance_task")
    if not finance_task:
        raise ValueError("Finance Agent was routed without a finance_task.")

    finance_instruction = _build_specialist_input(
        state["user_query"], finance_task, "Finance"
    )
    _debug("FINANCE_AGENT_INPUT", instruction=finance_instruction)
    finance_result = run_agent(
        "Finance Agent",
        lambda: finance_node_result(finance_instruction),
        task_ids["Finance Agent"],
    )
    _debug_result("FINANCE_AGENT_OUTPUT", finance_result)
    return {"finance_result": finance_result}


def research_node(state: FinanceAgentState):
    research_task = state.get("research_task")
    if not research_task:
        raise ValueError("Research Agent was routed without a research_task.")

    # Keep the original question separate from the specialist assignment.
    # Retrieval must be driven by the user's actual request; the assignment
    # provides scope and expected contribution without polluting search queries.
    research_state = dict(state)
    research_state["user_query"] = state["user_query"]
    research_state["research_task"] = research_task
    _debug(
        "RESEARCH_AGENT_INPUT",
        original_user_query=state["user_query"],
        research_task=research_task,
    )
    response = run_agent(
        "Research Agent",
        lambda: research_agent(research_state),
        task_ids["Research Agent"],
    )
    _debug_result("RESEARCH_AGENT_OUTPUT", response)
    return {
        "research_result": response["research_result"],
        "research_evidence": response["research_evidence"],
    }


def editor_node(state: FinanceAgentState):
    _debug(
        "EDITOR_INPUT_STATE",
        route=state.get("next_agent"),
        finance_result_present=state.get("finance_result") is not None,
        research_result_present=state.get("research_result") is not None,
        research_evidence_count=len(state.get("research_evidence") or []),
    )
    try:
        response = run_agent(
            "Editor Agent",
            lambda: editor_agent(state),
            task_ids["Editor Agent"],
        )
        _debug_result("EDITOR_AGENT_OUTPUT", response)
        return {
            "editor_result": response["editor_result"],
            "final_response": response["final_response"],
        }
    finally:
        progress.stop()


workflow = StateGraph(FinanceAgentState)
workflow.add_node("supervisor", supervisor_node)
workflow.add_node("finance", finance_node)
workflow.add_node("research", research_node)
workflow.add_node("editor", editor_node)
workflow.set_entry_point("supervisor")

workflow.add_conditional_edges(
    "supervisor",
    route_to_agent,
    {
        "finance": "finance",
        "research": "research",
    },
)

workflow.add_edge("finance", "editor")
workflow.add_edge("research", "editor")
workflow.add_edge("editor", END)

finance_workflow = workflow.compile()
