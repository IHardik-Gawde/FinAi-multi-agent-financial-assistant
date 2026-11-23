from langchain_ollama import ChatOllama

llm = ChatOllama(model="qwen3:1.7b", temperature=0)

response = llm.invoke("Explain what a financial analyst does in two sentences.")

print(response.content)
