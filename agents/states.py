from typing import TypedDict, Optional, Any


class FinanceAgentState(TypedDict):
    user_query: str
    next_agent: Optional[list[str]]

    # Tasks assigned by the Supervisor
    finance_task: Optional[str]
    research_task: Optional[str]

    # Structured specialist outputs
    finance_result: Optional[dict[str, Any]]
    research_result: Optional[dict[str, Any]]

    # Original retrieved document evidence
    research_evidence: Optional[list[dict[str, Any]]]

    editor_result: Optional[str]
    final_response: Optional[str]
