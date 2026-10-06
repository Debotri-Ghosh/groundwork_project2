# Shared image for both the FastAPI backend and the Streamlit frontend —
# docker-compose.yml runs this same image with two different commands.
FROM python:3.11-slim

WORKDIR /app

# requirements.txt uses psycopg2-binary (prebuilt wheel, no libpq-dev needed);
# build-essential is just a safety net in case any other dependency has no
# wheel for this platform and needs to compile from source.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Longer timeout/retries: this environment's network is slow for large
# downloads (torch, pulled in by sentence-transformers, is sizeable).
RUN pip install --no-cache-dir --default-timeout=180 --retries=10 -r requirements.txt

# Bake the embedding model into the image from a pre-fetched local cache
# (docker_hf_cache/) instead of downloading it at build/run time — this
# network can't reach huggingface.co at all (TLS interception without the
# right root CA), even from inside the build step. HF_HUB_OFFLINE forces
# sentence-transformers to use this cache and never attempt a network call.
ENV HF_HUB_OFFLINE=1
COPY docker_hf_cache/hub /root/.cache/huggingface/hub

COPY . .

# No CMD here — docker-compose.yml sets `command:` per service (api vs frontend).
