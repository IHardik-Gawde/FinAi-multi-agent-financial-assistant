import torch
from sentence_transformers import SentenceTransformer

print("CUDA available:", torch.cuda.is_available())

# Load embedding model on NVIDIA GPU
model = SentenceTransformer("BAAI/bge-base-en-v1.5", device="cuda")

# Sample financial text
sentences = [
    "Total revenue for October 2026 was INR 480,000.",
    "Total operating expenses were INR 312,000.",
    "The company recorded a net operating difference of INR 168,000.",
]

print("\nGenerating embeddings...")

embeddings = model.encode(sentences)

print("Embedding shape:", embeddings.shape)
print("Embedding device:", model.device)
print("First embedding:", embeddings[0][:5])
