# Groundwork — Project Documentation

## 1. What This Is

Groundwork is a Retrieval-Augmented Generation (RAG) system for answering natural-language questions about legal contracts. It is built on the real **CUAD v1** dataset (510 contracts, ~40 expert-annotated clause categories, CC BY 4.0 licensed). The one constraint the entire system is designed around: **every answer must be traceable back to real contract text, not the language model's own memory.** If the retrieved excerpts don't contain the answer, the system says so instead of guessing.

On top of that core, the system adds authentication, a multilingual question/answer layer, a browser-native read-aloud feature, and a fully containerized deployment.

---

## 2. Architecture at a Glance

```
┌──────────────┐      ┌───────────────────────┐      ┌──────────────────┐
│  Streamlit    │ HTTP │       FastAPI          │      │   PostgreSQL     │
│  frontend     │─────▶│       backend          │─────▶│ (contracts,      │
│  (app.py)     │◀─────│       (main.py)         │      │  clauses, users) │
└──────────────┘      │                         │      └──────────────────┘
                       │  ┌───────────────────┐  │
                       │  │  Qdrant             │ │ (vector search)
                       │  │  (semantic index)   │◀┘
                       │  └───────────────────┘  │
                       │                         │
                       │  ┌───────────────────┐  │
                       │  │  LLM (Groq, OpenAI- │ │ (generation + translation)
                       │  │  compatible API)    │ │
                       │  └───────────────────┘  │
                       └───────────────────────┘
```

The frontend never talks to the database, the vector index, or the LLM directly — it only ever calls the backend's HTTP API. That separation is why the UI could be redesigned, re-themed, and extended repeatedly without ever touching retrieval or generation logic.

---

## 3. End-to-End Workflow — What Happens When You Ask a Question

1. **You type a question** in the Streamlit UI (or pick a quick-prompt). A JWT (issued at login) is attached as a Bearer token on the request.
2. **Backend authenticates the request** (`auth.py`'s `get_current_user` dependency) — rejects with 401 if the token is missing, invalid, or expired.
3. **Language resolution.** If a specific language was selected, that's used directly. If "Auto-detect" is selected, `langdetect` identifies the question's language from the raw text.
4. **Translation to English (if needed).** The embedding model and the CUAD contracts are English-only, so a non-English question is translated to English via the LLM before anything else happens. If translation fails or returns empty, the user sees a clear warning and the system falls back to the original text.
5. **Embedding.** The (English) question is converted into a 384-dimensional vector using `all-MiniLM-L6-v2`.
6. **Vector search.** That vector is compared against every previously-indexed chunk's vector in Qdrant using cosine similarity; the top-k most similar chunks are returned, each carrying its source filename, chunk index, and similarity score.
7. **Prompt construction.** The retrieved chunks are inserted into a prompt that explicitly instructs the LLM: *answer ONLY from these excerpts; format as bullet points; bold key terms; include a short supporting quote per factual bullet; if the answer isn't in the excerpts, say so.*
8. **Generation.** The prompt goes to the LLM (Groq-hosted `openai/gpt-oss-20b`, via an OpenAI-compatible API), which returns the grounded, bulleted, quoted answer.
9. **Translation back (if needed).** If the question wasn't in English, the generated answer is translated into the user's language.
10. **Response assembly.** The backend returns the answer, the list of sources (filename, chunk index, score, full chunk text), the detected language (if any), and any language-related warning.
11. **Rendering.** The frontend splits each source's raw text into readable sentence-level points, bolds words that overlap with the question/answer, highlights the specific sentence(s) the LLM actually quoted, and always keeps the untouched original text one click away. A Listen button lets you hear the answer read aloud using the browser's built-in text-to-speech.

**Uploading a document** follows a parallel, shorter path: extract text (PDF/DOCX/TXT) → chunk → embed → upsert into the same Qdrant collection, tagged as an upload — immediately queryable alongside the CUAD contracts.

---

## 4. Every AI / ML Model Used — What, Where, and Why

This section goes roughly in pipeline order: the model used first (retrieval) through the model used last (speech output).

### 4.1 Embedding model — `all-MiniLM-L6-v2` (Sentence-Transformers)
- **What it is:** A distilled transformer (a compressed version of BERT-family models) trained specifically to produce sentence/paragraph embeddings — fixed-length numeric vectors (384 dimensions here) that place semantically similar text close together in vector space.
- **Where it's used:** `build_index.py` (embedding every contract chunk at index time) and `main.py`'s `retrieve()` function (embedding every incoming question at query time). Both sides must use the *same* model, or their vectors wouldn't be comparable.
- **Why this model specifically:**
  - It's small (~80MB) and fast on CPU — no GPU required, which matters since this runs in a plain Docker container, not a GPU-backed service.
  - It's a well-established, widely benchmarked baseline for semantic search — good enough quality for this use case without the cost/complexity of a larger embedding model.
  - It's small enough to bake directly into the Docker image (see §6), which turned out to matter a lot in practice — this network couldn't reach `huggingface.co` from inside a container, so a lightweight, cacheable model was the difference between "deployable" and "not."
  - **Known limitation, acknowledged rather than hidden:** it's a general-purpose model, not trained on legal text specifically. A domain-tuned alternative (e.g., a legal-BERT variant) is a documented future upgrade, not something claimed to already be in place.

### 4.2 Vector index — Qdrant (not itself an ML model, but the retrieval engine)
- **What it is:** A purpose-built vector database. It stores every chunk's embedding plus metadata (filename, chunk index, source text) and answers "find me the k most similar vectors" queries efficiently (cosine distance here).
- **Why Qdrant instead of, say, pgvector (bolted onto the existing Postgres):** a dedicated vector engine gives a simpler scaling story for semantic search specifically, kept separate from the transactional Postgres workload (contracts/clauses/users).
- **Why vector search alone, not hybrid search:** `rank-bm25` (a classic keyword-matching algorithm) is listed in `requirements.txt` from early planning but is **not actually wired into the pipeline** — retrieval is pure semantic/vector search today. This is stated plainly rather than implied otherwise; a hybrid BM25 + vector approach is a reasonable future improvement, not a claimed current feature.

### 4.3 The generative LLM — `openai/gpt-oss-20b`, served via Groq's OpenAI-compatible API
- **What it is:** A ~20-billion-parameter open-weight large language model, accessed through Groq's inference API (which exposes an OpenAI-compatible `/chat/completions` interface, so the same `openai` Python SDK works against it).
- **Where it's used (three distinct jobs, same model and client code, reused via a shared `_llm_chat` helper):**
  1. **Answer generation** — given the question + retrieved excerpts, produce the grounded, bulleted, quoted answer.
  2. **Question translation** — non-English question → English, before retrieval.
  3. **Answer translation** — English answer → the user's language, and on-demand excerpt translation via `/translate`.
- **Why an LLM for translation, instead of a dedicated translation API/library:** it reuses infrastructure that was already configured, tested, and proven reliable in this environment (Groq), with no new API key, no new network dependency, and no risk of hitting the same corporate-network blocks that affected `huggingface.co`. Modern instruction-tuned LLMs are also genuinely competent multilingual translators — not a compromise, a reasonable primary choice.
- **Why Groq specifically (over, say, calling OpenAI directly, or self-hosting):** very fast inference (Groq's LPU hardware), an API that's a drop-in match for the `openai` SDK (minimal integration work), and cost/accessibility suited to a project like this.
- **Pluggability:** `LLM_PROVIDER` in `.env` also supports `ollama` (a local, self-hosted LLM runner) as an alternative — useful for fully offline operation, at the cost of needing real local compute. Groq is the active choice in this deployment.
- **Honesty about reliability:** during testing, one Groq call returned an empty translation on a long, markdown-heavy answer — a transient flake (3/3 retries succeeded immediately after). The system is built to show a clear message and gracefully fall back to English in that case, rather than silently failing or crashing.

### 4.4 Language detection — `langdetect`
- **What it is:** A statistical language-identification library (a Python port of Google's n-gram-based language detector) — it classifies text by language using character n-gram frequency statistics and a Naive Bayes–style classifier. This is classical machine learning, not a neural network.
- **Where it's used:** `main.py`, to resolve "Auto-detect" into an actual ISO 639-1 language code before deciding whether translation is needed.
- **Why this instead of a neural/LLM-based language detector:**
  - It's deterministic, local, and has zero network dependency — no model download, no risk of hitting the same `huggingface.co` block that affected the embedding model.
  - It's fast enough to run on every request with no noticeable latency.
  - For the eight supported languages (English, Hindi, Bengali, Tamil, Telugu, Spanish, French, German), accuracy is reliably high — several use entirely distinct scripts (Devanagari, Bengali, Tamil, Telugu), and the remaining Latin-script languages have distinct enough n-gram profiles that a simple statistical classifier performs well. A heavier neural detector would add latency and a new dependency for no real accuracy gain at this scale.

### 4.5 Browser-native text-to-speech — Web Speech API (`speechSynthesis`)
- **What it is:** Not a model Groundwork trains, hosts, or even chooses — it's whatever speech-synthesis engine the end user's own browser/operating system provides (ranging from classic formant synthesis to on-device neural TTS, entirely platform-dependent).
- **Where it's used:** The "Listen" button on every answer, implemented via `st.components.v1.html` embedding plain JavaScript that calls `window.speechSynthesis`.
- **Why delegate to the browser instead of a cloud TTS API:** zero new backend service, zero new API key, zero per-request cost, and it works offline on the client side. The tradeoff, stated plainly: voice quality and language coverage are entirely out of Groundwork's control — if the user's browser has no Hindi voice installed, there is nothing the backend can do about it. The UI detects and reports that case explicitly ("No voice available for this language in your browser — using the default voice instead.") rather than failing silently.

### Summary table

| Stage | Model / Library | Type | Why |
|---|---|---|---|
| Retrieval | `all-MiniLM-L6-v2` | Neural (distilled transformer) embedding model | Small, fast, CPU-friendly, good-enough semantic search baseline |
| Retrieval infra | Qdrant | Vector database (not ML) | Dedicated, simpler scaling than bolting vectors onto Postgres |
| Generation | `openai/gpt-oss-20b` via Groq | Large language model | Fast inference, OpenAI-compatible, strong instruction-following for grounded/structured output |
| Translation | Same LLM as above | Large language model | Reuses proven infra; no new API key/service; LLMs translate well |
| Language detection | `langdetect` | Classical ML (n-gram + Naive Bayes) | Local, instant, no network dependency, accurate enough for 8 target languages |
| Read-aloud | Browser `speechSynthesis` | Delegated to client (unknown/varies) | Zero new service or cost; explicit fallback when unavailable |

---

## 5. Security

- Passwords are hashed with **bcrypt** before storage — never logged, never returned in any API response, never stored in plaintext.
- Sessions are **JWT**s (HS256), signed with a secret that must be set via environment variable — the backend refuses to start if it's missing, rather than silently using a weak default.
- `/query`, `/upload`, and `/translate` all require a valid Bearer token; `/health` stays public (no sensitive data, and the login screen needs to show backend status before anyone is signed in).
- Login failures return the same generic message whether the email doesn't exist or the password is wrong — no account enumeration.

---

## 6. Deployment

Four containers via `docker-compose.yml`: `postgres`, `qdrant`, `api` (FastAPI), and `frontend` (Streamlit). The `api` container's startup command runs the database bootstrap (`init_db.py` for contracts/clauses, `alembic upgrade head` for the `users` table) automatically and idempotently before starting the server, so a clean Postgres volume comes up fully migrated with no manual step.

**One environment-specific workaround, documented rather than hidden:** this network blocks `huggingface.co` even during the Docker build (TLS interception without the right root CA inside the minimal container), so the embedding model is baked into the image from a pre-downloaded local cache (`docker_hf_cache/`, committed to the repo, ~88MB) instead of being fetched at build or run time. `HF_HUB_OFFLINE=1` ensures the app never even attempts the network call. On a network without that restriction, the normal download would simply have worked — this isn't a universal requirement, just a resilience measure.

CUAD dataset ingestion (`extract_cuad.py`, `load_cuad.py`, `build_index.py`) remains a manual one-time step, run outside Docker — the raw dataset isn't redistributable per its license terms, so it was never part of the automated container startup.

---

## 7. What's Deliberately *Not* Claimed

In the interest of accuracy for anyone building a presentation from this document:
- No fine-tuning was performed on any model — the embedding model and the LLM are both used as-is, off the shelf.
- No hybrid keyword+vector search — despite `rank-bm25` being listed as a dependency, retrieval is pure vector similarity.
- No automated end-to-end test suite exists; verification throughout development was manual/scripted (curl-based regression checks, headless Streamlit `AppTest` runs), not a CI-enforced test pipeline.
- Translation quality was checked for fluency/structure, not certified by a native speaker for every supported language.
- Actual audio playback of the read-aloud feature was never heard — only the generated JavaScript's structure was verified (no browser/audio available in the development environment).
