from agents.finance_agent import finance_node_result

user_query = "Can you tell me whether Redwood Agritech is spending too much on its operations compared to the revenue it generates? "


print("\\n========== FINANCE NODE EXECUTION ==========")
answer = finance_node_result(user_query)

print("\\n" + "=" * 50)
print("          AI FINANCE AGENT")
print("=" * 50)
print("\\n" + str(answer))
print("\\n" + "=" * 50)
