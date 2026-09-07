"""
Phase 4: reads contracts from the database, splits each into overlapping
chunks, embeds them, and upserts into a local Qdrant collection.

Usage: python build_index.py
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

from init_db import Contract

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dev.db")
QDRANT_LOCAL_PATH = os.getenv("QDRANT_LOCAL_PATH", "./qdrant_local_data")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
COLLECTION_NAME = "groundwork_chunks"

CHUNK_WORDS = 300
CHUNK_OVERLAP_WORDS = 50


def chunk_text(text, chunk_words=CHUNK_WORDS, overlap_words=CHUNK_OVERLAP_WORDS):
    words = text.split()
    if not words:
        return []
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_words
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = end - overlap_words
    return chunks


def main():
    print("Loading embedding model...")
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    vector_size = model.get_sentence_embedding_dimension()

    print(f"Connecting to local Qdrant at {QDRANT_LOCAL_PATH}...")
    client = QdrantClient(path=QDRANT_LOCAL_PATH)

    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        print(f"Created collection '{COLLECTION_NAME}' (dim={vector_size})")
    else:
        print(f"Collection '{COLLECTION_NAME}' already exists — will add/overwrite points")

    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    contracts = session.query(Contract).filter(Contract.raw_text.isnot(None), Contract.raw_text != "").all()
    print(f"Chunking + embedding {len(contracts)} contracts...")

    point_id = 0
    batch = []
    BATCH_SIZE = 64
    total_chunks = 0

    for contract in contracts:
        chunks = chunk_text(contract.raw_text)
        if not chunks:
            continue
        embeddings = model.encode(chunks, show_progress_bar=False)

        for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
            batch.append(
                PointStruct(
                    id=point_id,
                    vector=vector.tolist(),
                    payload={
                        "contract_id": contract.contract_id,
                        "filename": contract.filename,
                        "document_name": contract.document_name,
                        "chunk_index": i,
                        "text": chunk,
                    },
                )
            )
            point_id += 1
            total_chunks += 1

            if len(batch) >= BATCH_SIZE:
                client.upsert(collection_name=COLLECTION_NAME, points=batch)
                batch = []

    if batch:
        client.upsert(collection_name=COLLECTION_NAME, points=batch)

    session.close()

    print(f"\nDone. Indexed {total_chunks} chunks from {len(contracts)} contracts.")
    print(f"Collection: {COLLECTION_NAME}, vector dim: {vector_size}")


if __name__ == "__main__":
    main()
