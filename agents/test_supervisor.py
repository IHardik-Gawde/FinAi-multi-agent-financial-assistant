import os

os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

from transformers.utils import logging

logging.disable_progress_bar()

from agents.supervisor import finance_workflow


response = finance_workflow.invoke(
    {
        "user_query": "Why are Greenline's operating expenses so high? Check the financial figures and see if there's any explanation in the reports",
        "finance_result": None,
        "research_result": None,
        "editor_result": None,
        "final_response": None,
    }
)

print("\nSelected agents:", response["next_agent"])
print("\n" + "=" * 55)
print("              AI FINANCE EMPLOYEE")
print("=" * 55)

print("\n" + response["final_response"])
