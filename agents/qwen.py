import ollama
import time

MODEL = "qwen3:4b-instruct"

prompt = """
Two companies have the following financial data:

Company A:
Revenue: 800000
Operating expenses: 560000

Company B:
Revenue: 600000
Operating expenses: 390000

Calculate the operating expense ratio for both companies.
Rank them from highest to lowest ratio.
Identify the more expense-efficient company.

Keep the answer concise and show the calculations.
"""

start = time.perf_counter()

response = ollama.chat(
    model=MODEL,
    messages=[{"role": "user", "content": prompt}],
    think=False,
    keep_alive="10m",
    options={"num_predict": 200},
    stream=False,
)

total_time = time.perf_counter() - start

print("\n--- MODEL RESPONSE ---\n")
print(response["message"]["content"])


# Ollama reports durations in nanoseconds
def to_seconds(value):
    return (value or 0) / 1_000_000_000


load_time = to_seconds(response.get("load_duration"))
prompt_time = to_seconds(response.get("prompt_eval_duration"))
generation_time = to_seconds(response.get("eval_duration"))

prompt_tokens = response.get("prompt_eval_count", 0)
generated_tokens = response.get("eval_count", 0)

prompt_speed = prompt_tokens / prompt_time if prompt_time else 0
generation_speed = generated_tokens / generation_time if generation_time else 0

print("\n--- DETAILED PERFORMANCE ---")
print(f"Total execution time:       {total_time:.2f} seconds")
print(f"Model loading time:         {load_time:.2f} seconds")
print(f"Prompt evaluation time:     {prompt_time:.2f} seconds")
print(f"Prompt tokens:              {prompt_tokens}")
print(f"Prompt processing speed:    {prompt_speed:.2f} tokens/sec")
print(f"Generation time:            {generation_time:.2f} seconds")
print(f"Generated tokens:           {generated_tokens}")
print(f"Generation speed:           {generation_speed:.2f} tokens/sec")
