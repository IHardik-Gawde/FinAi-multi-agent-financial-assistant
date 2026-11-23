from agents.research_agent import research_agent

test_state = {
    "user_query": "What was the company's employee headcount in October 2026?"
}

print("\n" + "=" * 55)
print("          AI FINANCE EMPLOYEE - RAG TEST")
print("=" * 55)

response = research_agent(test_state)

print("\nResearch Agent Response:")
print(response["research_result"])

print("\n" + "=" * 55)
