from agents.editor_agent import editor_agent


test_state = {
    "user_query": "Rewrite this professionally: Our revenue was ₹230,000, expenses were ₹85,000, and the net difference was ₹145,000."
}

response = editor_agent(test_state)

print("\n" + "=" * 50)
print("          AI EDITOR AGENT")
print("=" * 50)

print("\n" + response["final_response"])

print("\n" + "=" * 50)
