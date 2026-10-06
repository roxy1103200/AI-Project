"""Download the fixed embedding model before starting memory services."""

import os

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

from app.memory import MODEL, MODEL_REVISION

if __name__ == "__main__":
    load_dotenv(".env")
    target = os.getenv("MEMORY_MODEL_PATH", "../data/models/bge-small-zh-v1.5")
    SentenceTransformer(MODEL, revision=MODEL_REVISION, device="cpu").save(target)
    print(f"Memory embedding model saved to {target}")
