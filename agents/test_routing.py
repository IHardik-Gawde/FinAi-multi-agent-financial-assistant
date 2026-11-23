from agents.supervisor import supervisor_node

test_queries = [
    "Which invoices are overdue?",
    "What was SilverOak's revenue in April 2026 according to its financial report?",
    "What was SilverOak's revenue in April 2026, and what were our total expenses in the internal database?",
]

for query in test_queries:
    print("\n" + "=" * 60)
    print("QUERY:", query)

    result = supervisor_node({"user_query": query})

    print("ROUTING RESULT:", result["next_agent"])
