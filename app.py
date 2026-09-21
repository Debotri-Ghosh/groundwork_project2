import time
from datetime import datetime

import requests
import streamlit as st

API_URL = "http://localhost:8000"
UPLOAD_TYPES = ["pdf", "docx", "txt"]

QUICK_PROMPTS = {
    "Termination rights": "Can either party terminate this agreement, and under what conditions?",
    "Governing law": "What is the governing law of the agreement?",
    "Insurance requirements": "What insurance is a party required to maintain under the agreement?",
    "Non-compete": "Is there a non-compete restriction, and how long does it last?",
    "Payment terms": "What are the payment terms outlined in the contract?",
}

# ---------------- Theme presets ----------------
THEMES = {
    "Midnight Violet": dict(
        bg="#0e1117", panel="#161b26", panel2="#1c2333", border="#2a3245",
        accent="#7c5cff", accent_soft="rgba(124, 92, 255, 0.16)",
        text="#e6e8ee", muted="#9aa3b5", good="#2fbf9f", warn="#e8a33d", bad="#e4572e",
    ),
    "Aurora Teal": dict(
        bg="#0a1720", panel="#0f2530", panel2="#123240", border="#1d4756",
        accent="#21d4b4", accent_soft="rgba(33, 212, 180, 0.16)",
        text="#e5f4f1", muted="#8fb3ac", good="#21d4b4", warn="#e8a33d", bad="#ff6b6b",
    ),
    "Ivory Premium": dict(
        bg="#f7f8fb", panel="#ffffff", panel2="#f1f3f9", border="#e2e6ef",
        accent="#6c4cff", accent_soft="rgba(108, 76, 255, 0.10)",
        text="#1c2333", muted="#6b7280", good="#0f9d78", warn="#c9821a", bad="#d1483a",
    ),
}

DENSITY = {
    "Comfortable": dict(card_pad="16px 20px", gap="12px", font_body="0.92rem"),
    "Compact": dict(card_pad="10px 14px", gap="7px", font_body="0.85rem"),
}

st.set_page_config(
    page_title="Groundwork — Contract Assistant",
    page_icon="📄",
    layout="wide",
)

# ---------------- Session state ----------------
st.session_state.setdefault("history", [])
st.session_state.setdefault("uploaded_files", [])
st.session_state.setdefault("theme_name", "Midnight Violet")
st.session_state.setdefault("density_name", "Comfortable")


def confidence_tier(score, palette):
    if score >= 0.5:
        return "High confidence", palette["good"]
    elif score >= 0.3:
        return "Medium confidence", palette["warn"]
    return "Low confidence", palette["bad"]


def run_query(question: str, top_k: int):
    entry = {"question": question, "ts": datetime.now().strftime("%H:%M")}
    start = time.perf_counter()
    try:
        response = requests.post(
            f"{API_URL}/query",
            json={"question": question, "top_k": top_k},
            timeout=120,
        )
        response.raise_for_status()
        result = response.json()
        entry["error"] = None
        entry["answer"] = result.get("answer", "No answer returned.")
        entry["sources"] = result.get("sources", [])
        entry["elapsed"] = time.perf_counter() - start
    except requests.exceptions.ConnectionError:
        entry["error"] = "Could not connect to the FastAPI backend. Make sure it is running at " + API_URL + "."
    except requests.exceptions.Timeout:
        entry["error"] = "The request timed out. The backend/LLM took too long to respond."
    except requests.RequestException as e:
        entry["error"] = f"API request failed: {e}"
    except ValueError:
        entry["error"] = "The API returned an invalid response."
    st.session_state.history.append(entry)


def build_transcript_md():
    lines = ["# Groundwork — Conversation Export", ""]
    for e in st.session_state.history:
        lines.append(f"### 🧑 {e['ts']} — {e['question']}")
        if e.get("error"):
            lines.append(f"> ⚠️ {e['error']}")
        else:
            lines.append(e["answer"])
            for i, s in enumerate(e.get("sources", []), start=1):
                lines.append(f"\n**Source {i}:** `{s['filename']}` (chunk {s['chunk_index']}, score {s['score']:.3f})")
                lines.append(f"> {s['text'][:400]}")
        lines.append("\n---\n")
    return "\n".join(lines)


# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown("## 📄 Groundwork")
    st.caption("Contract Intelligence Console")

    with st.expander("🎨 Appearance", expanded=True):
        theme_name = st.selectbox("Theme", list(THEMES.keys()),
                                   index=list(THEMES.keys()).index(st.session_state["theme_name"]))
        density_name = st.select_slider("Density", options=list(DENSITY.keys()),
                                         value=st.session_state["density_name"])
        st.session_state["theme_name"] = theme_name
        st.session_state["density_name"] = density_name

    with st.expander("🔍 Retrieval settings", expanded=True):
        top_k = st.slider("Number of sources", min_value=1, max_value=10, value=5,
                           help="How many contract chunks to retrieve per question.")
        score_threshold = st.slider("Minimum relevance score", 0.0, 1.0, 0.0, 0.05,
                                     help="Hide sources scoring below this cosine-similarity threshold.")
        sort_by = st.selectbox("Sort sources by", ["Relevance (default)", "Filename (A–Z)", "Chunk order"])

    with st.expander("📎 Documents", expanded=False):
        uploaded_file = st.file_uploader(
            "Attach a document", type=UPLOAD_TYPES,
            help="Attach a .pdf, .docx or .txt — it gets indexed so you can ask questions about it.",
            label_visibility="collapsed",
        )
        if uploaded_file is not None and st.session_state.get("last_upload") != uploaded_file.name:
            with st.spinner(f"Indexing {uploaded_file.name} ..."):
                try:
                    resp = requests.post(
                        f"{API_URL}/upload",
                        files={"file": (uploaded_file.name, uploaded_file.getvalue())},
                        timeout=300,
                    )
                    resp.raise_for_status()
                    info = resp.json()
                    st.session_state["last_upload"] = uploaded_file.name
                    if uploaded_file.name not in st.session_state["uploaded_files"]:
                        st.session_state["uploaded_files"].append(uploaded_file.name)
                    st.toast(f"{info['filename']} ready — {info['chunks_indexed']} chunks indexed.", icon="📎")
                except requests.exceptions.ConnectionError:
                    st.error("Could not connect to the backend for upload.")
                except requests.exceptions.Timeout:
                    st.error("Upload timed out.")
                except requests.RequestException as e:
                    st.error(f"Upload failed: {e}")

        if st.session_state["uploaded_files"]:
            st.caption("Indexed this session:")
            for fn in st.session_state["uploaded_files"]:
                st.markdown(f"<span class='gw-file-chip'>📄 {fn}</span>", unsafe_allow_html=True)
        else:
            st.caption("No documents uploaded yet.")

    with st.expander("⚙️ System status", expanded=False):
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
            st.caption(f"Start the FastAPI server at {API_URL}.")

    st.markdown("---")
    col_clear, col_export = st.columns(2)
    with col_clear:
        if st.button("🗑️ Clear chat", use_container_width=True):
            st.session_state.history = []
            st.rerun()
    with col_export:
        st.download_button(
            "⬇️ Export", data=build_transcript_md(), file_name="groundwork_conversation.md",
            mime="text/markdown", use_container_width=True, disabled=not st.session_state.history,
        )

# ---------------- Theme CSS ----------------
palette = THEMES[st.session_state["theme_name"]]
dens = DENSITY[st.session_state["density_name"]]

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=Inter:wght@400;500;600&display=swap');

    html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}
    .stApp {{ background: {palette['bg']}; color: {palette['text']}; }}

    h1, h2, h3 {{ font-family: 'Sora', sans-serif !important; }}

    .gw-hero {{
        padding: 8px 0 4px 0;
    }}
    .gw-hero h1 {{
        font-size: 2.1rem;
        font-weight: 800;
        margin: 0;
        background: linear-gradient(90deg, {palette['text']}, {palette['accent']});
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }}
    .gw-hero p {{ color: {palette['muted']}; margin-top: 4px; font-size: 0.95rem; }}

    div[data-testid="stTextAreaTextArea"], div[data-testid="stChatInput"] textarea {{
        background: {palette['panel']} !important;
        border: 1px solid {palette['border']} !important;
        border-radius: 14px !important;
        color: {palette['text']} !important;
    }}

    .stButton > button, [data-testid="baseButton-primary"] {{
        border-radius: 12px;
        border: 1px solid {palette['border']};
        transition: all 0.15s ease;
        color: {palette['text']};
        background: {palette['panel']};
    }}
    .stButton > button:hover {{
        border-color: {palette['accent']};
        background: {palette['accent_soft']};
        transform: translateY(-1px);
    }}

    div[data-testid="stFileUploaderDropzone"] {{
        background: {palette['panel']};
        border: 1px dashed {palette['border']};
        border-radius: 14px;
    }}

    .gw-chip-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 6px 0 18px 0; }}

    .gw-file-chip {{
        display: inline-block;
        background: {palette['panel2']};
        border: 1px solid {palette['border']};
        color: {palette['muted']};
        border-radius: 999px;
        padding: 3px 10px;
        font-size: 0.78rem;
        margin: 3px 4px 0 0;
    }}

    .gw-card {{
        background: {palette['panel']};
        border: 1px solid {palette['border']};
        border-radius: 12px;
        padding: {dens['card_pad']};
        margin-bottom: {dens['gap']};
        transition: border-color 0.15s ease;
    }}
    .gw-card:hover {{ border-color: {palette['accent']}; }}
    .gw-card-header {{
        display: flex; justify-content: space-between; align-items: center; gap: 8px;
    }}
    .gw-filename {{ font-weight: 600; color: {palette['text']}; font-size: {dens['font_body']}; }}
    .gw-chip {{
        background: {palette['accent_soft']};
        color: {palette['accent']};
        border-radius: 999px;
        padding: 2px 10px;
        font-size: 0.75rem;
        white-space: nowrap;
    }}
    .gw-card-text {{
        color: {palette['muted']};
        font-size: {dens['font_body']};
        margin-top: 6px;
        line-height: 1.45;
    }}

    .gw-stat-row {{ display: flex; gap: 10px; margin: 8px 0 14px 0; flex-wrap: wrap; }}
    .gw-stat {{
        background: {palette['panel2']};
        border: 1px solid {palette['border']};
        border-radius: 10px;
        padding: 6px 12px;
        font-size: 0.78rem;
        color: {palette['muted']};
    }}
    .gw-badge {{
        border-radius: 999px;
        padding: 3px 12px;
        font-size: 0.78rem;
        font-weight: 600;
        color: #0b0d12;
    }}

    section[data-testid="stSidebar"] {{
        background: {palette['panel']};
        border-right: 1px solid {palette['border']};
    }}

    .gw-answer {{
        background: {palette['panel2']};
        border: 1px solid {palette['border']};
        border-radius: 12px;
        padding: 16px 20px;
        color: {palette['text']};
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------- Hero header ----------------
st.markdown(
    """
    <div class="gw-hero">
        <h1>Groundwork</h1>
        <p>Ask questions about the indexed contract library — grounded, cited, and traceable.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------- Quick prompts ----------------
st.caption("Quick prompts")
chip_cols = st.columns(len(QUICK_PROMPTS))
for col, (label, prompt_text) in zip(chip_cols, QUICK_PROMPTS.items()):
    with col:
        if st.button(label, use_container_width=True, key=f"quick_{label}"):
            run_query(prompt_text, top_k)
            st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# ---------------- Chat history ----------------
for entry in st.session_state.history:
    with st.chat_message("user"):
        st.write(entry["question"])

    with st.chat_message("assistant"):
        if entry.get("error"):
            st.error(entry["error"])
            continue

        st.markdown(f'<div class="gw-answer">{entry["answer"]}</div>', unsafe_allow_html=True)

        sources = entry.get("sources", [])
        filtered = [s for s in sources if s["score"] >= score_threshold]

        if sort_by == "Filename (A–Z)":
            filtered = sorted(filtered, key=lambda s: s["filename"])
        elif sort_by == "Chunk order":
            filtered = sorted(filtered, key=lambda s: s["chunk_index"])

        top_score = max((s["score"] for s in sources), default=0.0)
        tier_label, tier_color = confidence_tier(top_score, palette)

        st.markdown(
            f"""
            <div class="gw-stat-row">
                <span class="gw-badge" style="background:{tier_color};">{tier_label}</span>
                <span class="gw-stat">⏱ {entry.get('elapsed', 0):.1f}s</span>
                <span class="gw-stat">📚 {len(sources)} source(s) retrieved</span>
                <span class="gw-stat">🎯 top score {top_score:.3f}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if not sources:
            st.info("No sources returned.")
        elif not filtered:
            st.warning(f"All {len(sources)} source(s) scored below your {score_threshold:.2f} threshold. "
                       "Lower it in the sidebar to see them.")
        else:
            for i, source in enumerate(filtered, start=1):
                preview = source["text"][:300]
                if len(source["text"]) > 300:
                    preview += "…"
                st.markdown(
                    f"""
                    <div class="gw-card">
                        <div class="gw-card-header">
                            <span class="gw-filename">{i}. {source['filename']}</span>
                            <span class="gw-chip">chunk {source['chunk_index']} · score {source['score']:.3f}</span>
                        </div>
                        <div class="gw-card-text">{preview}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if len(source["text"]) > 300:
                    with st.expander("Show full excerpt"):
                        st.code(source["text"], language=None, wrap_lines=True)

# ---------------- Chat input ----------------
if prompt := st.chat_input("Ask about the indexed contracts…"):
    run_query(prompt, top_k)
    st.rerun()
