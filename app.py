import requests
import streamlit as st

API_URL = "http://localhost:8000"
UPLOAD_TYPES = ["pdf", "docx", "txt"]

st.set_page_config(
    page_title="Groundwork — Contract Assistant",
    page_icon="📄",
    layout="wide",
)

# ---------------- Dark, modern chat-style CSS (visuals only) ----------------
st.markdown(
    """
    <style>
    :root {
        --bg: #0e1117;
        --panel: #161b26;
        --panel-2: #1c2333;
        --border: #2a3245;
        --accent: #7c5cff;
        --accent-soft: rgba(124, 92, 255, 0.15);
        --text: #e6e8ee;
        --muted: #9aa3b5;
    }
    /* App background */
    .stApp { background: var(--bg); color: var(--text); }

    /* Rounded question box */
    div[data-testid="stTextAreaTextArea"] {
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 14px;
        color: var(--text);
    }
    div[data-testid="stTextAreaTextArea"]:focus {
        border-color: var(--accent);
        box-shadow: 0 0 0 2px var(--accent-soft);
    }

    /* Buttons: rounded + hover states */
    .stButton > button, [data-testid="baseButton-primary"] {
        border-radius: 12px;
        border: 1px solid var(--border);
        transition: all 0.15s ease;
    }
    .stButton > button:hover {
        border-color: var(--accent);
        background: var(--accent-soft);
        transform: translateY(-1px);
    }
    [data-testid="baseButton-primary"] {
        background: var(--accent);
        border-color: var(--accent);
        color: white;
    }

    /* File uploader chip */
    div[data-testid="stFileUploaderDropzone"] {
        background: var(--panel);
        border: 1px dashed var(--border);
        border-radius: 14px;
    }
    div[data-testid="stFileUploaderDropzone"]:hover {
        border-color: var(--accent);
        background: var(--panel-2);
    }

    /* Source cards */
    .gw-card {
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 12px 16px;
        margin-bottom: 10px;
        transition: border-color 0.15s ease;
    }
    .gw-card:hover { border-color: var(--accent); }
    .gw-card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 8px;
    }
    .gw-filename { font-weight: 600; color: var(--text); font-size: 0.92rem; }
    .gw-chip {
        background: var(--accent-soft);
        color: #b8a7ff;
        border-radius: 999px;
        padding: 2px 10px;
        font-size: 0.75rem;
        white-space: nowrap;
    }
    .gw-card-text {
        color: var(--muted);
        font-size: 0.85rem;
        margin-top: 6px;
        line-height: 1.45;
    }

    /* Sidebar polish */
    section[data-testid="stSidebar"] {
        background: var(--panel);
        border-right: 1px solid var(--border);
    }

    /* Answer bubble */
    .gw-answer {
        background: var(--panel-2);
        border: 1px solid var(--border);
        border-left: 3px solid var(--accent);
        border-radius: 12px;
        padding: 16px 20px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📄 Groundwork — Contract Intelligence")
st.caption("Ask questions about the indexed contract documents — or attach your own.")

# ---------------- Sidebar (settings) ----------------
with st.sidebar:
    st.markdown("## ⚙️ Settings")
    st.caption("Retrieval options")
    top_k = st.slider(
        "Number of sources",
        min_value=1,
        max_value=10,
        value=5,
        help="How many contract chunks to retrieve per question.",
    )

    st.markdown(
        '<hr style="border:none;border-top:1px solid #2a3245;margin:14px 0"/>',
        unsafe_allow_html=True,
    )

    st.markdown("### 🖥️ Backend")
    try:
        health = requests.get(f"{API_URL}/health", timeout=5)
        if health.ok:
            st.success("API is online")
            provider = health.json().get("llm_provider", "unknown")
            st.caption(f"LLM provider: `{provider}`")
        else:
            st.error("API returned an error")
    except requests.RequestException:
        st.error("API is offline")
        st.caption("Start the FastAPI server on port 8000.")

# ---------------- Attachment (like ChatGPT/Claude) ----------------
uploaded_file = st.file_uploader(
    "📎 Attach a document",
    type=UPLOAD_TYPES,
    help="Attach a .pdf, .docx or .txt — it gets indexed so you can ask questions about it.",
)

if uploaded_file is not None:
    # Index each new upload once (compare against what we already sent)
    if st.session_state.get("uploaded_name") != uploaded_file.name:
        with st.spinner(f"📎 Indexing **{uploaded_file.name}** ..."):
            try:
                resp = requests.post(
                    f"{API_URL}/upload",
                    files={"file": (uploaded_file.name, uploaded_file.getvalue())},
                    timeout=300,
                )
                resp.raise_for_status()
                info = resp.json()
                st.session_state["uploaded_name"] = uploaded_file.name
                st.toast(
                    f"✅ {info['filename']} ready — {info['chunks_indexed']} chunks indexed.",
                    icon="📎",
                )
                st.success(info["message"])
            except requests.exceptions.ConnectionError:
                st.error(
                    "Could not connect to the FastAPI backend for upload. "
                    "Make sure it is running at http://localhost:8000."
                )
            except requests.exceptions.Timeout:
                st.error("Upload timed out. The backend took too long to index the document.")
            except requests.RequestException as e:
                # Includes 4xx responses (unsupported type, empty file) via raise_for_status
                detail = ""
                try:
                    detail = resp.json().get("detail", "")
                except Exception:
                    pass
                st.error(f"Upload failed: {detail or e}")
            except ValueError:
                st.error("The backend returned an invalid response for the upload.")

# ---------------- Chat input ----------------
question = st.text_area(
    "Your contract question",
    placeholder="Example: Can we claim EOT for delayed work?",
    height=120,
    label_visibility="collapsed",
)

col_spacer, col_ask = st.columns([6, 1])
with col_ask:
    ask_clicked = st.button("🔍 Ask", type="primary", use_container_width=True)

if ask_clicked:
    if not question.strip():
        st.warning("Please enter a question.")
    else:
        with st.spinner("Searching contracts and generating answer..."):
            try:
                response = requests.post(
                    f"{API_URL}/query",
                    json={
                        "question": question,
                        "top_k": top_k,
                    },
                    timeout=120,
                )

                response.raise_for_status()
                result = response.json()

                st.markdown("### 💬 Answer")
                st.markdown(
                    f'<div class="gw-answer">{result.get("answer", "No answer returned.")}</div>',
                    unsafe_allow_html=True,
                )

                sources = result.get("sources", [])

                st.markdown("### 📚 Sources")
                if not sources:
                    st.info("No sources returned.")
                else:
                    for i, source in enumerate(sources, start=1):
                        st.markdown(
                            f"""
                            <div class="gw-card">
                                <div class="gw-card-header">
                                    <span class="gw-filename">{i}. {source['filename']}</span>
                                    <span class="gw-chip">chunk {source['chunk_index']} · score {source['score']:.3f}</span>
                                </div>
                                <div class="gw-card-text">{source['text']}</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                        # Full excerpt kept accessible, same fields as before
                        with st.expander("Show full excerpt"):
                            st.write(source["text"])

            except requests.exceptions.ConnectionError:
                st.error(
                    "Could not connect to the FastAPI backend. "
                    "Make sure it is running at http://localhost:8000."
                )

            except requests.exceptions.Timeout:
                st.error(
                    "The request timed out. The backend/LLM took too long to respond."
                )

            except requests.RequestException as e:
                st.error(f"API request failed: {e}")

            except ValueError:
                st.error("The API returned an invalid response.")