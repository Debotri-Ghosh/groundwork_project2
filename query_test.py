"""
Tests the Qdrant index built by build_index.py — runs a real search query
and shows what comes back.

Usage: python query_test.py "your question here"
"""
import os
import sys
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient

load_dotenv()

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
COLLECTION_NAME = "groundwork_chunks"

DEFAULT_QUERY = "What are the termination for convenience terms?"


def main():
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else DEFAULT_QUERY
    print(f"Query: {query}\n")

    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    query_vector = model.encode(query).tolist()

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=5,
    ).points

    print(f"Top {len(results)} results:\n")
    for i, hit in enumerate(results, 1):
        payload = hit.payload
        preview = payload["text"][:200].replace("\n", " ")
        print(f"{i}. score={hit.score:.4f} | {payload['filename']} (chunk {payload['chunk_index']})")
        print(f"   {preview}...\n")


if __name__ == "__main__":
    main()
