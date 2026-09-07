"""
Phase 5: FastAPI backend for Groundwork.
Exposes POST /query -> retrieves relevant contract chunks, asks the LLM
to answer using them, returns the answer + sources.

Run with: uvicorn main:app --reload --port 8000
Test with: curl or the /docs Swagger UI at http://localhost:8000/docs
"""
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient

load_dotenv()

QDRANT_LOCAL_PATH = os.getenv("QDRANT_LOCAL_PATH", "./qdrant_local_data")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
COLLECTION_NAME = "groundwork_chunks"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
TOP_K = 5

app = FastAPI(title="Groundwork API")

# Loaded once at startup, reused across requests
embed_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
qdrant = QdrantClient(path=QDRANT_LOCAL_PATH)

# --- LLM client setup, based on LLM_PROVIDER in .env ---
if LLM_PROVIDER == "openai":
    from openai import OpenAI
    llm_client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
    )
    LLM_MODEL = os.getenv("OPENAI_MODEL", "llama-3.1-8b-instant")  # adjust to your Groq model
elif LLM_PROVIDER == "ollama":
    import ollama
    llm_client = ollama.Client(host=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    LLM_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
else:
    llm_client = None
    LLM_MODEL = None


class QueryRequest(BaseModel):
    question: str
    top_k: int = TOP_K


class Source(BaseModel):
    filename: str
    chunk_index: int
    score: float
    text: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]


def retrieve(question: str, top_k: int):
    query_vector = embed_model.encode(question).tolist()
    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
    ).points
    return results


def build_prompt(question: str, chunks) -> str:
    context = "\n\n---\n\n".join(
        f"[Source: {c.payload['filename']}]\n{c.payload['text']}" for c in chunks
    )
    return (
        "You are a contract analysis assistant. Answer the question using ONLY "
        "the contract excerpts below. If the answer isn't in the excerpts, say so.\n\n"
        f"Excerpts:\n{context}\n\n"
        f"Question: {question}\n\nAnswer:"
    )


def generate_answer(question: str, chunks) -> str:
    if llm_client is None:
        return "(No LLM configured — set LLM_PROVIDER in .env to 'openai' or 'ollama')"

    prompt = build_prompt(question, chunks)

    if LLM_PROVIDER == "openai":
        response = llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    elif LLM_PROVIDER == "ollama":
        response = llm_client.chat(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return response["message"]["content"]

    return "(Unsupported LLM_PROVIDER)"


@app.get("/health")
def health():
    return {"status": "ok", "llm_provider": LLM_PROVIDER}


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    chunks = retrieve(request.question, request.top_k)
    answer = generate_answer(request.question, chunks)
    sources = [
        Source(
            filename=c.payload["filename"],
            chunk_index=c.payload["chunk_index"],
            score=c.score,
            text=c.payload["text"][:300],
        )
        for c in chunks
    ]
    return QueryResponse(answer=answer, sources=sources)
