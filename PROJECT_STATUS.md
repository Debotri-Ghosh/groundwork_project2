# Groundwork — Project Status & Handoff Notes

## What This Is

Groundwork is an end-to-end Retrieval-Augmented Generation (RAG) system for answering natural-language questions about legal contracts, grounded in the real **CUAD v1** dataset (510 contracts, ~40 expert-annotated clause categories, CC BY 4.0 licensed). Answers are generated only from retrieved, cited contract text — not from the LLM's memory — so every answer is traceable back to a specific contract and clause.

## Completed Phases

### Phase 1 — Dataset Extraction
`extract_cuad.py` — Extracts `CUAD_v1.zip` on Windows, working around the 260-character path limit (prefixes paths with `\\?\`, no admin rights needed). Skips the large `full_contract_pdf/` tree entirely (not needed — the project uses `full_contract_txt/*` and `master_clauses.csv` instead), avoiding most long-path failures. Reports extracted/skipped/failed counts.

### Phase 2 — Database Schema & Ingestion (PostgreSQL + SQLAlchemy)
- `init_db.py` — Defines two related tables: `contracts` (contract_id, unique filename, document_name, raw_text) and `clauses` (clause_id, FK → contract_id, category, extracted_text, answer), with cascade-delete. Forces UTF-8 stdout for Windows cp1252 console compatibility.
- `load_cuad.py` — Loads `master_clauses.csv` + the `.txt` contract files into Postgres. Walks nested `Part_I/II/III` subfolders to build a filename→path index; parses CUAD's Python-list-style quote strings via `ast.literal_eval`; pairs each clause category with its `-Answer` column (including CUAD's one inconsistently-spaced `"- Answer"` column); deduplicates repeated CSV rows; tracks contracts missing a matching `.txt` file.
- `verify_db.py` — Verification: table listing, row counts, a spot-checked sample contract + its clauses, and a join query (contracts with ≥10 clauses found).

### Phase 3 — Exploratory Data Analysis
`eda.py` — Loads `CUAD_v1.json` + `master_clauses.csv`. Computes per-contract character/word/paragraph counts, dataset-wide summary statistics, data-quality checks (empty contracts, duplicate/missing titles), and annotation-category analysis. Outputs to `eda_results/`: `contract_statistics.csv`, `annotation_distribution.csv`, and three charts (contract length distribution, top-15 annotation categories, annotations-per-contract) — plus a full console capture in `eda_output.txt`.

### Phase 4 — Vector Indexing (Qdrant + Sentence-Transformers)
`build_index.py` — Reads contracts with non-empty text from Postgres, splits each into overlapping word chunks (300 words, 50-word overlap), embeds with `all-MiniLM-L6-v2` (384-dim), and batch-upserts (batch size 64) into a Qdrant collection (`groundwork_chunks`, COSINE distance, created if absent) with payload `{contract_id, filename, document_name, chunk_index, text}`.
`query_test.py` — CLI sanity check: embeds a question, retrieves top-5 from Qdrant, prints score/filename/chunk/preview.

### Phase 5 — FastAPI Backend
`main.py` exposes:
- `GET /health` — status + active LLM provider
- `POST /query` — retrieves top-k chunks via Qdrant, builds a strictly-grounded prompt ("answer ONLY from these excerpts; say so if the answer isn't present"), sends to the configured LLM (pluggable: Groq/OpenAI-compatible via `OPENAI_*` env vars, or local Ollama), returns `answer` + `sources` (filename, chunk index, cosine score, text preview)
- `POST /upload` — accepts a PDF/DOCX/TXT file, extracts text (`text_extract.py`), chunks + embeds it the same way as CUAD contracts, and indexes it into the same Qdrant collection (tagged `source: "upload"`) so it's immediately queryable

### Phase 6 — Streamlit Frontend
`app.py` — Dark-themed, wide-layout UI ("Groundwork — Contract Intelligence"). Sidebar shows live backend health + active LLM provider and a top-k retrieval slider. Main area: file attachment (calls `/upload`), a question box, an Ask button, and the answer rendered with expandable, score-labeled source cards. Handles connection errors, timeouts, and invalid responses distinctly.

## Infrastructure

- **`docker-compose.yml`** — Two services: Qdrant (ports 6333 REST / 6334 gRPC, named volume, TCP healthcheck) and Postgres 16 (host port **5433→5432**, since native Windows Postgres already occupies 5432 on this machine; env-driven credentials; `pg_isready` healthcheck).
- **`.env`** (gitignored) / `groundwork.env.example` (committed template) — `LLM_PROVIDER`, Groq-compatible `OPENAI_*` vars, Ollama fallback vars, `EMBEDDING_MODEL_NAME`, `QDRANT_HOST`/`PORT`, full Postgres `DATABASE_URL` + credentials.
- **`check_setup.py`** — 5-point health check: env vars, Qdrant server connection, Postgres connectivity, embedding model load, LLM provider config presence.
- **`.gitignore`** — excludes `venv/`, `__pycache__/`, `.env` (secrets), and `data/` (large, and CUAD's terms don't permit redistribution).
- **`requirements.txt`** — fully pinned: FastAPI, uvicorn, Streamlit, PyMuPDF/pdfplumber/python-docx, pandas/numpy, qdrant-client, sentence-transformers, rank-bm25, openai, ollama, SQLAlchemy/Alembic/psycopg2-binary, pydantic.

## Outstanding / Immediate Next Steps

1. **Git commit & push is pending** — a review pass was done but blocked by Plan mode (state-changing commands like `git add`/`commit`/`push` were disallowed). This needs to be completed as the very next action.
2. Structured end-to-end evaluation across a representative set of test questions (beyond single spot-checks).
3. FleetMind (second, separate project — predictive maintenance on the APS Failure/Scania Trucks dataset) — environment scaffolded, implementation not yet started.
4. Consider a domain-specific embedding model (e.g. LEGAL-BERT) as a future upgrade, per literature review findings.

## Repository Layout

```
groundwork/
├── main.py               # FastAPI backend (/query, /upload, /health)
├── app.py                 # Streamlit frontend (dark theme)
├── text_extract.py        # PDF/DOCX/TXT extraction for uploads
├── init_db.py             # SQLAlchemy schema
├── load_cuad.py            # CUAD CSV + text → Postgres
├── extract_cuad.py         # CUAD zip extraction (Windows long-path safe)
├── build_index.py          # Chunk + embed + index into Qdrant
├── query_test.py           # CLI retrieval test
├── verify_db.py            # Database verification
├── check_setup.py          # Environment health check
├── eda.py                  # Dataset exploratory analysis
├── eda_results/             # EDA outputs (CSVs, PNGs)
├── docker-compose.yml       # Postgres + Qdrant containers
├── requirements.txt
├── groundwork.env.example
├── .gitignore
└── .env                    # not committed
```
