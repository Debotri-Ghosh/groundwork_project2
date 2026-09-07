"""
Run this after setup to confirm everything is wired correctly.
Works whether you're on Docker (Qdrant/Postgres servers) or running
the no-Docker fallback (local embedded Qdrant + SQLite).
Usage: python check_setup.py
"""
import os
from dotenv import load_dotenv

load_dotenv()


def check(name, ok, detail=""):
    status = "✅" if ok else "❌"
    print(f"{status}  {name}" + (f"  ({detail})" if detail else ""))


print("\n--- Groundwork Setup Check ---\n")

# 1. Env vars loaded
check("APP_ENV loaded", os.getenv("APP_ENV") is not None, os.getenv("APP_ENV"))

# 2. Qdrant connection — tries server mode first, falls back to local embedded mode
try:
    from qdrant_client import QdrantClient

    qdrant_host = os.getenv("QDRANT_HOST")
    qdrant_local_path = os.getenv("QDRANT_LOCAL_PATH")

    if qdrant_host:
        client = QdrantClient(host=qdrant_host, port=int(os.getenv("QDRANT_PORT", 6333)))
        client.get_collections()
        check("Qdrant connection (server mode)", True)
    elif qdrant_local_path:
        client = QdrantClient(path=qdrant_local_path)
        client.get_collections()
        check("Qdrant connection (local embedded mode)", True, qdrant_local_path)
    else:
        check("Qdrant connection", False, "set QDRANT_HOST or QDRANT_LOCAL_PATH in .env")
except Exception as e:
    check("Qdrant connection", False, str(e))

# 3. Database connection — Postgres or SQLite, both via DATABASE_URL
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
print("Note: DATABASE_URL using sqlite:// and QDRANT_LOCAL_PATH set means you're")
print("running in no-Docker fallback mode — switch back to the server URLs in")
print(".env once Docker/WSL access is available. No other code changes needed.\n")
