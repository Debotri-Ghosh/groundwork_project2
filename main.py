"""
Phase 5: FastAPI backend for Groundwork.
Exposes POST /query -> retrieves relevant contract chunks, asks the LLM
to answer using them, returns the answer + sources.

Run with: uvicorn main:app --reload --port 8000
Test with: curl or the /docs Swagger UI at http://localhost:8000/docs
"""
import os
import uuid
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from langdetect import detect as detect_language
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from auth import User, get_current_user, router as auth_router
from build_index import chunk_text  # same 300-word / 50-overlap chunker
from text_extract import extract_text

load_dotenv()

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
COLLECTION_NAME = "groundwork_chunks"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
TOP_K = 5

# Relevance filtering (Phase 1). Calibrated against four real questions —
# see PROJECT_DOCUMENTATION.md for the observed score clusters:
#   insurance requirements  -> top 0.705 (clearly relevant)
#   non-compete duration    -> top 0.463 (relevant, weaker)
#   EOT for delayed work    -> top 0.576 (relevant)
#   "capital of France"     -> top 0.262 (irrelevant control)
# 0.35 sits in the ~0.09 gap between the irrelevant and relevant clusters.
MIN_SCORE = float(os.getenv("MIN_SCORE", "0.35"))
RELATIVE_SCORE_RATIO = 0.70  # keep only chunks within 70% of the top score

# ISO 639-1 code -> display name. Contracts and the embedding model are
# English-only, so every non-English question is translated to English
# before retrieval, and the answer translated back before it's returned.
SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}

app = FastAPI(title="Groundwork API")
app.include_router(auth_router)

# Loaded once at startup, reused across requests
embed_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

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
    language: str = "auto"  # "auto", or an ISO code from SUPPORTED_LANGUAGES


class Source(BaseModel):
    filename: str
    chunk_index: int
    score: float
    text: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source]
    detected_language: Optional[str] = None
    language_error: Optional[str] = None
    evidence: str = "None"  # "Strong" | "Moderate" | "Weak" | "None"


class TranslateRequest(BaseModel):
    text: str
    target_language: str  # ISO code from SUPPORTED_LANGUAGES


class TranslateResponse(BaseModel):
    translated_text: str


def retrieve(question: str, top_k: int):
    query_vector = embed_model.encode(question).tolist()
    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=top_k,
    ).points
    return results


def filter_relevant_chunks(chunks):
    """The top-k slider is a maximum, not a guarantee — drop chunks that
    don't clear an absolute floor (MIN_SCORE) or a relative floor (70% of
    the top score among this candidate set). Never backfills from outside
    the original top-k candidates; only ever narrows them."""
    if not chunks:
        return []
    top_score = chunks[0].score
    relative_floor = RELATIVE_SCORE_RATIO * top_score
    return [c for c in chunks if c.score >= MIN_SCORE and c.score >= relative_floor]


def evidence_label(top_score: float) -> str:
    if top_score >= 0.55:
        return "Strong"
    if top_score >= 0.45:
        return "Moderate"
    if top_score >= MIN_SCORE:
        return "Weak"
    return "None"


def build_prompt(question: str, chunks) -> str:
    context = "\n\n---\n\n".join(
        f"[Source: {c.payload['filename']}]\n{c.payload['text']}" for c in chunks
    )
    return (
        "You are a contract analysis assistant. Answer the question using ONLY "
        "the contract excerpts below. If the answer isn't in the excerpts, say so "
        "plainly instead of guessing — do not add a bullet for anything not "
        "actually stated in the excerpts.\n\n"
        "Format the answer as a Markdown bulleted list (one point per line, "
        "each starting with '- '):\n"
        "  - Bold key terms with **double asterisks** — amounts, dates, "
        "durations, and party names.\n"
        "  - Each bullet that makes a specific factual claim must include a "
        "short supporting quote from the excerpt in quotation marks, so the "
        "claim is directly traceable back to the source text.\n\n"
        f"Excerpts:\n{context}\n\n"
        f"Question: {question}\n\nAnswer:"
    )


def _llm_chat_once(prompt: str) -> str:
    if LLM_PROVIDER == "openai":
        response = llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""

    elif LLM_PROVIDER == "ollama":
        response = llm_client.chat(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        return response["message"]["content"] or ""

    return ""


def _llm_chat(prompt: str) -> str:
    """Single place that actually calls the configured LLM — used for both
    answer generation and translation, so provider-branching lives once.
    Retries once on an empty completion: observed intermittently (roughly
    1 in 4 calls during testing) from this Groq-hosted model, unrelated to
    prompt content — a second attempt reliably succeeds."""
    if llm_client is None:
        return "(No LLM configured — set LLM_PROVIDER in .env to 'openai' or 'ollama')"
    if LLM_PROVIDER not in ("openai", "ollama"):
        return "(Unsupported LLM_PROVIDER)"

    content = _llm_chat_once(prompt)
    if not content.strip():
        content = _llm_chat_once(prompt)
    return content

    return "(Unsupported LLM_PROVIDER)"


def generate_answer(question: str, chunks) -> str:
    return _llm_chat(build_prompt(question, chunks))


def translate_text(text: str, target_language_name: str) -> str:
    """Translate arbitrary text with the same LLM used for answers — no new
    service, no new API key. Used for question/answer translation in
    /query and for the on-demand excerpt translation in /translate."""
    prompt = (
        f"Translate the following text into {target_language_name}. "
        "Output ONLY the translation itself — no preamble, no quotation "
        "marks, no explanation.\n\nText:\n" + text
    )
    return (_llm_chat(prompt) or "").strip()


@app.get("/health")
def health():
    return {"status": "ok", "llm_provider": LLM_PROVIDER}


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest, current_user: User = Depends(get_current_user)):
    detected = None
    language_error = None

    # ---- Resolve the effective language: explicit selection, or detect it ----
    if request.language and request.language != "auto":
        if request.language not in SUPPORTED_LANGUAGES:
            supported = ", ".join(SUPPORTED_LANGUAGES.values())
            return QueryResponse(
                answer="", sources=[],
                language_error=f"'{request.language}' isn't a supported language code. Supported: {supported}.",
            )
        effective_lang = request.language
    else:
        try:
            effective_lang = detect_language(request.question) if request.question.strip() else "en"
        except Exception:
            effective_lang = "en"  # detection can fail on very short/ambiguous text
        detected = effective_lang
        if effective_lang not in SUPPORTED_LANGUAGES:
            supported = ", ".join(SUPPORTED_LANGUAGES.values())
            return QueryResponse(
                answer="", sources=[], detected_language=effective_lang,
                language_error=f"Detected language '{effective_lang}' isn't supported yet. Supported: {supported}.",
            )

    # ---- Question -> English (retrieval/embedding model are English-only) ----
    english_question = request.question
    if effective_lang != "en":
        try:
            translated_q = translate_text(request.question, "English")
            if not translated_q:
                language_error = "Translating your question returned an empty result; answering using your original text."
            else:
                english_question = translated_q
        except Exception as e:
            language_error = f"Translating your question failed ({e}); answering using your original text."

    # ---- Retrieve (top_k is a maximum candidate set), then filter for relevance ----
    chunks = retrieve(english_question, request.top_k)
    relevant = filter_relevant_chunks(chunks)
    top_score = chunks[0].score if chunks else 0.0
    evidence = evidence_label(top_score if relevant else 0.0)

    if not relevant:
        # Nothing cleared the relevance bar -- don't spend an LLM call on it.
        return QueryResponse(
            answer="No strong evidence found in the contracts.",
            sources=[], detected_language=detected, language_error=language_error,
            evidence="None",
        )

    # Group passages by contract: stable sort by filename, then chunk order,
    # so same-contract chunks are adjacent for the frontend to render under
    # one heading.
    relevant = sorted(relevant, key=lambda c: (c.payload["filename"], c.payload["chunk_index"]))

    answer = generate_answer(english_question, relevant)

    # ---- Answer -> user's language ----
    if effective_lang != "en":
        try:
            translated_a = translate_text(answer, SUPPORTED_LANGUAGES[effective_lang])
            if not translated_a:
                note = "Translating the answer returned an empty result; showing the English answer instead."
                language_error = f"{language_error} {note}" if language_error else note
            else:
                answer = translated_a
        except Exception as e:
            note = f"Translating the answer failed ({e}); showing the English answer instead."
            language_error = f"{language_error} {note}" if language_error else note

    sources = [
        Source(
            filename=c.payload["filename"],
            chunk_index=c.payload["chunk_index"],
            score=c.score,
            text=c.payload["text"],
        )
        for c in relevant
    ]
    return QueryResponse(
        answer=answer, sources=sources, detected_language=detected,
        language_error=language_error, evidence=evidence,
    )


@app.post("/translate", response_model=TranslateResponse)
def translate_endpoint(request: TranslateRequest, current_user: User = Depends(get_current_user)):
    """On-demand translation for a single source excerpt (or any text) —
    separate from /query's own question/answer translation, so excerpts are
    only ever translated when a user explicitly asks for one."""
    if request.target_language not in SUPPORTED_LANGUAGES:
        supported = ", ".join(SUPPORTED_LANGUAGES.values())
        raise HTTPException(status_code=400, detail=f"Unsupported target language. Supported: {supported}.")
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="No text provided to translate.")

    try:
        translated = translate_text(request.text, SUPPORTED_LANGUAGES[request.target_language])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Translation failed: {e}")

    if not translated:
        raise HTTPException(status_code=502, detail="Translation returned an empty result.")

    return TranslateResponse(translated_text=translated)


@app.post("/upload")
async def upload(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    """Extract text from an uploaded document, chunk + embed it with the
    same chunker/model as the CUAD index, and upsert into the same
    Qdrant collection so /query can retrieve from it immediately."""
    data = await file.read()

    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        raw_text = extract_text(file.filename, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Text extraction failed: {e}")

    chunks = chunk_text(raw_text)
    if not chunks:
        raise HTTPException(status_code=400, detail="Document produced no chunks.")

    embeddings = embed_model.encode(chunks, show_progress_bar=False)

    points = [
        PointStruct(
            id=str(uuid.uuid4()),  # UUID ids: never collide with CUAD's integer ids
            vector=vector.tolist(),
            payload={
                "contract_id": None,
                "filename": file.filename,
                "document_name": file.filename,
                "chunk_index": i,
                "text": chunk,
                "source": "upload",  # distinguishes uploads from CUAD contracts
            },
        )
        for i, (chunk, vector) in enumerate(zip(chunks, embeddings))
    ]

    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)

    return {
        "filename": file.filename,
        "chunks_indexed": len(chunks),
        "message": f"Indexed {len(chunks)} chunks from {file.filename}. You can now ask questions about it.",
    }
