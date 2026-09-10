"""
Run this after setup to confirm everything is wired correctly.
Expects Docker services (Qdrant server + Postgres) started via:
    docker compose up -d
Usage: python check_setup.py
"""
import os
import sys
from dotenv import load_dotenv

# Windows consoles (cp1252) can't print ✅/❌ — force UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()


def check(name, ok, detail=""):
    status = "✅" if ok else "❌"
    print(f"{status}  {name}" + (f"  ({detail})" if detail else ""))


print("\n--- Groundwork Setup Check ---\n")

# 1. Env vars loaded
check("APP_ENV loaded", os.getenv("APP_ENV") is not None, os.getenv("APP_ENV"))

# 2. Qdrant connection — server mode (Docker)
try:
    from qdrant_client import QdrantClient

    qdrant_host = os.getenv("QDRANT_HOST", "localhost")
    qdrant_port = int(os.getenv("QDRANT_PORT", 6333))

    client = QdrantClient(host=qdrant_host, port=qdrant_port)
    client.get_collections()
    check("Qdrant connection (server mode)", True, f"{qdrant_host}:{qdrant_port}")
except Exception as e:
    check("Qdrant connection (server mode)", False, str(e))

# 3. Database connection — Postgres via DATABASE_URL
try:
    from sqlalchemy import create_engine, text

    db_url = os.getenv("DATABASE_URL")
    engine = create_engine(db_url)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    check("Database connection", True, db_url.split("://")[0])
except Exception as e:
    check("Database connection", False, str(e))

# 4. Embedding model loads
try:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2"))
    vec = model.encode("test sentence")
    check("Embedding model loads", len(vec) > 0, f"dim={len(vec)}")
except Exception as e:
    check("Embedding model loads", False, str(e))

# 5. LLM provider reachable (only checks config presence, not a live call)
provider = os.getenv("LLM_PROVIDER", "not set")
if provider == "azure_openai":
    ok = bool(os.getenv("AZURE_OPENAI_API_KEY")) and bool(os.getenv("AZURE_OPENAI_ENDPOINT"))
    check("Azure OpenAI config present", ok)
elif provider == "ollama":
    ok = bool(os.getenv("OLLAMA_BASE_URL"))
    check("Ollama config present", ok)
elif provider == "openai":
    ok = bool(os.getenv("OPENAI_API_KEY"))
    check("OpenAI config present", ok)
else:
    check("LLM_PROVIDER set", False, "set LLM_PROVIDER in .env")

print("\nIf everything above is ✅, you're ready to start Phase 2 (data ingestion + chunking).\n")
print("Running in Docker mode: Qdrant server + Postgres via docker compose.\n")