from agents.research_agent import research_agent


response = research_agent(
    {
        "user_query": "Prepare a comparative financial risk assessment of all indexed companies. Consider revenue, expenses, receivables, overdue invoices, and available reporting periods. Clearly distinguish documented facts from unavailable information"
    }
)

print("\n" + "=" * 50)
print("          AI RESEARCH AGENT")
print("=" * 50)

print("\n" + response["research_result"])

print("\n" + "=" * 50)
