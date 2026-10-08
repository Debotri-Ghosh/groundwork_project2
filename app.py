import html
import json
import os
import re
import time
from datetime import datetime
from difflib import SequenceMatcher

import requests
import streamlit as st

API_URL = os.environ.get("GROUNDWORK_API_URL", "http://localhost:8000")
UPLOAD_TYPES = ["pdf", "docx", "txt"]

QUICK_PROMPTS = {
    "Termination rights": "Can either party terminate this agreement, and under what conditions?",
    "Governing law": "What is the governing law of the agreement?",
    "Insurance requirements": "What insurance is a party required to maintain under the agreement?",
    "Non-compete": "Is there a non-compete restriction, and how long does it last?",
    "Payment terms": "What are the payment terms outlined in the contract?",
}

# Must match main.py's SUPPORTED_LANGUAGES (ISO 639-1 codes); "Auto-detect"
# is a frontend-only option that main.py sees as language="auto".
LANGUAGES = {
    "Auto-detect": "auto",
    "English": "en",
    "Hindi": "hi",
    "Bengali": "bn",
    "Tamil": "ta",
    "Telugu": "te",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
}
LANGUAGE_NAMES_BY_CODE = {v: k for k, v in LANGUAGES.items()}

# ISO 639-1 -> a BCP-47 tag the browser's speechSynthesis voices actually use.
LANG_TO_BCP47 = {
    "en": "en-US", "hi": "hi-IN", "bn": "bn-IN", "ta": "ta-IN",
    "te": "te-IN", "es": "es-ES", "fr": "fr-FR", "de": "de-DE",
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
st.session_state.setdefault("token", None)
st.session_state.setdefault("user_email", None)


def auth_headers():
    return {"Authorization": f"Bearer {st.session_state['token']}"}


def render_login_screen():
    """Blocks the rest of the app until the user signs in or signs up.
    Mirrors the error-handling style already used for /query and /upload."""
    st.markdown(
        """
        <div style="max-width:420px;margin:10vh auto 0 auto;">
            <h1 style="font-size:2rem;font-weight:800;margin-bottom:0;">📄 Groundwork</h1>
            <p style="color:#9aa3b5;margin-top:4px;">Sign in to access the contract assistant.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _, center, _ = st.columns([1, 2, 1])
    with center:
        try:
            health = requests.get(f"{API_URL}/health", timeout=5)
            if health.ok:
                st.caption("🟢 Backend is online")
            else:
                st.caption("🔴 Backend returned an error")
        except requests.RequestException:
            st.caption(f"🔴 Backend is offline — start it at {API_URL}")

        login_tab, signup_tab = st.tabs(["Log in", "Sign up"])

        with login_tab:
            with st.form("login_form"):
                email = st.text_input("Email", key="login_email")
                password = st.text_input("Password", type="password", key="login_password")
                submitted = st.form_submit_button("Log in", use_container_width=True, type="primary")
            if submitted:
                try:
                    resp = requests.post(
                        f"{API_URL}/auth/login",
                        json={"email": email, "password": password},
                        timeout=15,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    st.session_state["token"] = data["access_token"]
                    st.session_state["user_email"] = data["email"]
                    st.rerun()
                except requests.exceptions.ConnectionError:
                    st.error(f"Could not connect to the backend. Make sure it is running at {API_URL}.")
                except requests.exceptions.Timeout:
                    st.error("The request timed out.")
                except requests.exceptions.HTTPError:
                    detail = ""
                    try:
                        detail = resp.json().get("detail", "")
                    except Exception:
                        pass
                    st.error(detail or "Login failed.")
                except requests.RequestException as e:
                    st.error(f"Login failed: {e}")

        with signup_tab:
            with st.form("signup_form"):
                new_email = st.text_input("Email", key="signup_email")
                new_password = st.text_input(
                    "Password", type="password", key="signup_password",
                    help="At least 8 characters.",
                )
                submitted_signup = st.form_submit_button("Create account", use_container_width=True)
            if submitted_signup:
                try:
                    resp = requests.post(
                        f"{API_URL}/auth/signup",
                        json={"email": new_email, "password": new_password},
                        timeout=15,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    st.session_state["token"] = data["access_token"]
                    st.session_state["user_email"] = data["email"]
                    st.rerun()
                except requests.exceptions.ConnectionError:
                    st.error(f"Could not connect to the backend. Make sure it is running at {API_URL}.")
                except requests.exceptions.Timeout:
                    st.error("The request timed out.")
                except requests.exceptions.HTTPError:
                    detail = ""
                    try:
                        detail = resp.json().get("detail", "")
                    except Exception:
                        pass
                    st.error(detail or "Sign up failed.")
                except requests.RequestException as e:
                    st.error(f"Sign up failed: {e}")


if not st.session_state["token"]:
    render_login_screen()
    st.stop()


# ---------------- Excerpt point-splitting & citation highlighting ----------------
# Display-only heuristics — never touch the raw grounding text itself, just
# how it's segmented and annotated in the UI.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
_BARE_MARKER_RE = re.compile(r"^[\d/.\s]+$")
_QUOTE_RE = re.compile(r"[“\"]([^”\"]{15,400})[”\"]")


def split_into_points(text: str) -> list:
    """Break a raw contract excerpt into readable points on sentence
    boundaries, folding bare clause numbers/dates (e.g. "16.",
    "2/8/2017 16.") forward into the sentence that follows them instead of
    emitting them as their own stray point."""
    text = (text or "").strip()
    if not text:
        return []
    raw_parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]
    merged, buffer = [], ""
    for part in raw_parts:
        buffer = f"{buffer} {part}".strip() if buffer else part
        if _BARE_MARKER_RE.match(buffer) or len(buffer) < 16:
            continue
        merged.append(buffer)
        buffer = ""
    if buffer:
        merged.append(buffer)
    return merged or [text]


def extract_quotes(answer: str) -> list:
    """Pull the quoted spans the LLM cited in its bulleted answer, so we can
    point back to exactly where in the source they came from."""
    return [q.strip() for q in _QUOTE_RE.findall(answer or "") if len(q.strip()) > 14]


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def point_is_cited(point: str, quotes: list) -> bool:
    """Whether this excerpt point is (closely) the text the answer quoted."""
    np = _normalize(point)
    if not np:
        return False
    for q in quotes:
        nq = _normalize(q)
        if not nq:
            continue
        if nq in np or np in nq:
            return True
        if SequenceMatcher(None, nq[:120], np[:120]).ratio() > 0.72:
            return True
    return False


def highlight_html(escaped_text: str, term: str, bg_color: str) -> str:
    """Wrap case-insensitive matches of `term` in <mark>. Expects text that's
    already HTML-escaped, and only ever adds markup, never raw user text."""
    if not term:
        return escaped_text
    pattern = re.compile(re.escape(html.escape(term)), re.IGNORECASE)
    return pattern.sub(
        lambda m: f"<mark style='background:{bg_color};color:#111;border-radius:3px;padding:0 2px;'>{m.group(0)}</mark>",
        escaped_text,
    )


_WORD_RE = re.compile(r"[A-Za-z]{4,}")
_OVERLAP_STOPWORDS = {
    "this", "that", "these", "those", "with", "from", "shall", "will",
    "under", "which", "where", "when", "what", "there", "their", "about",
    "into", "such", "than", "then", "have", "been", "were", "does", "each",
    "between", "agreement", "party", "parties", "excerpts", "excerpt",
}


def extract_overlap_terms(*texts: str) -> set:
    """Words (4+ letters) shared between the question/answer and an excerpt,
    minus common filler — used to bold what's actually relevant at a glance,
    distinct from point_is_cited's whole-sentence citation match."""
    words = set()
    for t in texts:
        for w in _WORD_RE.findall(t or ""):
            wl = w.lower()
            if wl not in _OVERLAP_STOPWORDS:
                words.add(wl)
    return words


def bold_overlap_html(escaped_text: str, terms: set) -> str:
    """Bold occurrences of any term in `terms` within already-escaped text."""
    if not terms:
        return escaped_text
    pattern = re.compile(r"\b(" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")\b", re.IGNORECASE)
    return pattern.sub(lambda m: f"<b>{m.group(0)}</b>", escaped_text)


# ---------------- Read-aloud (Phase C) ----------------
def strip_markdown_for_speech(text: str) -> str:
    """Remove Markdown syntax (bold/italic/headers/bullets/blockquotes/code)
    so the browser's TTS reads words, not punctuation. Does not touch the
    displayed answer — only the copy sent to speechSynthesis."""
    t = text or ""
    t = re.sub(r"```.*?```", " ", t, flags=re.DOTALL)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"\*([^*]+)\*", r"\1", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.MULTILINE)
    t = re.sub(r"^\s*>\s*", "", t, flags=re.MULTILINE)
    t = re.sub(r"\n{2,}", ". ", t)
    t = re.sub(r"\n", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def render_listen_widget(uid: str, text: str, lang_code: str, palette: dict):
    """A self-contained Listen/Pause/Stop + speed control using only the
    browser's built-in Web Speech API — no backend call, no API key."""
    clean_text = strip_markdown_for_speech(text)
    if not clean_text:
        return
    bcp47 = LANG_TO_BCP47.get(lang_code or "en", "en-US")
    text_json = json.dumps(clean_text).replace("</script>", "<\\/script>")
    btn_style = (
        f"background:{palette['accent_soft']};color:{palette['accent']};"
        "border:none;border-radius:8px;padding:5px 12px;font-size:0.82rem;"
        "cursor:pointer;margin-right:6px;"
    )
    html_code = f"""
    <div style="font-family:Inter,sans-serif;background:{palette['panel']};
                border:1px solid {palette['border']};border-radius:10px;
                padding:10px 14px;color:{palette['text']};box-sizing:border-box;">
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
        <button id="play-{uid}" style="{btn_style}">▶ Listen</button>
        <button id="pause-{uid}" style="{btn_style}">⏸ Pause</button>
        <button id="stop-{uid}" style="{btn_style}">⏹ Stop</button>
        <label style="font-size:0.78rem;color:{palette['muted']};margin-left:6px;">
          Speed
          <input id="speed-{uid}" type="range" min="0.5" max="2" step="0.1" value="1"
                 style="vertical-align:middle;">
        </label>
        <span id="speedval-{uid}" style="font-size:0.78rem;color:{palette['muted']};">1.0x</span>
      </div>
      <div id="status-{uid}" style="font-size:0.75rem;color:{palette['muted']};margin-top:6px;">Ready.</div>
    </div>
    <script>
    (function() {{
      const text = {text_json};
      const targetLang = "{bcp47}";
      const statusEl = document.getElementById("status-{uid}");

      function pickVoice() {{
        const voices = window.speechSynthesis.getVoices();
        if (!voices || voices.length === 0) return null;
        let v = voices.find(v => v.lang.toLowerCase() === targetLang.toLowerCase());
        if (!v) v = voices.find(v => v.lang.toLowerCase().startsWith(targetLang.split('-')[0].toLowerCase()));
        return v || null;
      }}

      function withVoices(cb) {{
        const voices = window.speechSynthesis.getVoices();
        if (voices && voices.length > 0) {{ cb(); return; }}
        window.speechSynthesis.onvoiceschanged = () => cb();
      }}

      if (!('speechSynthesis' in window)) {{
        statusEl.textContent = "Your browser doesn't support text-to-speech.";
        ["play-{uid}", "pause-{uid}", "stop-{uid}"].forEach(id => {{
          document.getElementById(id).disabled = true;
        }});
        return;
      }}

      document.getElementById("play-{uid}").onclick = function() {{
        if (window.speechSynthesis.paused && window.speechSynthesis.speaking) {{
          window.speechSynthesis.resume();
          statusEl.textContent = "Speaking…";
          return;
        }}
        withVoices(function() {{
          const voice = pickVoice();
          window.speechSynthesis.cancel();
          const utterance = new SpeechSynthesisUtterance(text);
          utterance.lang = targetLang;
          utterance.rate = parseFloat(document.getElementById("speed-{uid}").value);
          if (voice) {{
            utterance.voice = voice;
            statusEl.textContent = "Speaking with " + voice.name + "…";
          }} else {{
            statusEl.textContent = "No voice available for this language in your browser — using the default voice instead.";
          }}
          utterance.onend = function() {{ statusEl.textContent = "Finished."; }};
          utterance.onerror = function(e) {{ statusEl.textContent = "Speech error: " + e.error; }};
          window.speechSynthesis.speak(utterance);
        }});
      }};

      document.getElementById("pause-{uid}").onclick = function() {{
        if (window.speechSynthesis.speaking) {{
          window.speechSynthesis.pause();
          statusEl.textContent = "Paused.";
        }}
      }};

      document.getElementById("stop-{uid}").onclick = function() {{
        window.speechSynthesis.cancel();
        statusEl.textContent = "Stopped.";
      }};

      document.getElementById("speed-{uid}").oninput = function(e) {{
        document.getElementById("speedval-{uid}").textContent = parseFloat(e.target.value).toFixed(1) + "x";
      }};
    }})();
    </script>
    """
    st.components.v1.html(html_code, height=100)


def run_query(question: str, top_k: int, language: str = "auto"):
    entry = {"question": question, "ts": datetime.now().strftime("%H:%M")}
    start = time.perf_counter()
    try:
        with st.spinner("Searching contracts and drafting a grounded answer…"):
            response = requests.post(
                f"{API_URL}/query",
                json={"question": question, "top_k": top_k, "language": language},
                headers=auth_headers(),
                timeout=120,
            )
        if response.status_code == 401:
            st.session_state["token"] = None
            st.session_state["user_email"] = None
            st.warning("Your session expired. Please log in again.")
            st.rerun()
        response.raise_for_status()
        result = response.json()
        entry["error"] = None
        entry["answer"] = result.get("answer", "No answer returned.")
        entry["sources"] = result.get("sources", [])
        entry["detected_language"] = result.get("detected_language")
        entry["language_error"] = result.get("language_error")
        entry["evidence"] = result.get("evidence", "None")
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
    st.caption(f"Signed in as **{st.session_state['user_email']}**")
    if st.button("🚪 Log out", use_container_width=True):
        st.session_state["token"] = None
        st.session_state["user_email"] = None
        st.rerun()
    st.markdown("---")

    with st.expander("🎨 Appearance", expanded=True):
        theme_name = st.selectbox("Theme", list(THEMES.keys()),
                                   index=list(THEMES.keys()).index(st.session_state["theme_name"]))
        density_name = st.select_slider("Density", options=list(DENSITY.keys()),
                                         value=st.session_state["density_name"])
        st.session_state["theme_name"] = theme_name
        st.session_state["density_name"] = density_name

    with st.expander("🌐 Language", expanded=False):
        language_label = st.selectbox(
            "Question & answer language", list(LANGUAGES.keys()), index=0,
            help="Auto-detect works out the language of each question you type. "
                 "Picking a language explicitly answers in that language regardless.",
        )
        language_code = LANGUAGES[language_label]
        st.caption("Contracts are English-only — your question is translated to "
                   "English for retrieval, then the answer is translated back.")

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
                        headers=auth_headers(),
                        timeout=300,
                    )
                    if resp.status_code == 401:
                        st.session_state["token"] = None
                        st.session_state["user_email"] = None
                        st.warning("Your session expired. Please log in again.")
                        st.rerun()
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

    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------- Hero header ----------------
st.markdown(
    f"""
    <div class="gw-hero">
        <h1>Groundwork</h1>
        <p>Answers from your contracts, with the evidence attached.</p>
        <div style="margin-top:8px;">
            <span class="gw-stat">📚 510 real contracts</span>
            <span class="gw-stat">🔗 Cited answers</span>
            <span class="gw-stat">🌐 8 languages</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("❓ Why Groundwork vs. a general chatbot?"):
    st.markdown(
        """
| | A general chatbot | Groundwork |
|---|---|---|
| **Source of answers** | The model's own memory | Your indexed contract documents |
| **Citations** | None, or unverifiable | The exact clause/sentence is shown |
| **When evidence is missing** | May guess anyway | Says "no strong evidence found" |
| **Scope** | Whatever was pasted into the chat | All 510 contracts, persistently indexed |
| **Control** | Black box | Login, swappable LLM, auditable sources |
        """
    )

# ---------------- Quick prompts ----------------
st.caption("Quick prompts")
chip_cols = st.columns(len(QUICK_PROMPTS))
for col, (label, prompt_text) in zip(chip_cols, QUICK_PROMPTS.items()):
    with col:
        if st.button(label, use_container_width=True, key=f"quick_{label}"):
            run_query(prompt_text, top_k, language_code)
            st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# ---------------- Chat history ----------------
POINTS_SHOWN_BY_DEFAULT = 5

for msg_idx, entry in enumerate(st.session_state.history):
    with st.chat_message("user"):
        st.write(entry["question"])

    with st.chat_message("assistant"):
        if entry.get("error"):
            st.error(entry["error"])
            continue

        if entry.get("language_error"):
            st.warning(f"🌐 {entry['language_error']}")

        if not entry.get("answer"):
            # Unsupported language: nothing else to render for this turn.
            continue

        # Header row for the answer card: detected-language indicator on the
        # left, Listen/Pause/Stop control on the right.
        answer_lang = entry.get("detected_language") or (language_code if language_code != "auto" else "en")
        header_l, header_r = st.columns([3, 2])
        with header_l:
            if entry.get("detected_language") and entry["detected_language"] != "en":
                detected_name = LANGUAGE_NAMES_BY_CODE.get(entry["detected_language"], entry["detected_language"])
                st.caption(f"🌐 Detected language: {detected_name}")
        with header_r:
            render_listen_widget(f"listen-{msg_idx}", entry["answer"], answer_lang, palette)

        # A plain st.markdown wrapped in a raw <div> would NOT parse markdown
        # inside it (CommonMark treats content in a raw HTML block as literal) —
        # a container keeps the bordered look while still rendering the LLM's
        # bulleted/bolded markdown correctly.
        with st.container(border=True):
            st.markdown(entry["answer"])

        quotes = extract_quotes(entry["answer"])

        sources = entry.get("sources", [])
        filtered = [s for s in sources if s["score"] >= score_threshold]

        if sort_by == "Filename (A–Z)":
            filtered = sorted(filtered, key=lambda s: s["filename"])
        elif sort_by == "Chunk order":
            filtered = sorted(filtered, key=lambda s: s["chunk_index"])

        # Group by contract for display: keeps whatever ordering sort_by just
        # established within each contract, but makes every contract's
        # chunks adjacent instead of interleaved (e.g. under "Chunk order").
        _grouped = {}
        for _s in filtered:
            _grouped.setdefault(_s["filename"], []).append(_s)
        filtered = [_s for _group in _grouped.values() for _s in _group]

        top_score = max((s["score"] for s in sources), default=0.0)
        evidence = entry.get("evidence", "None")
        evidence_colors = {
            "Strong": palette["good"], "Moderate": palette["warn"],
            "Weak": palette["bad"], "None": palette["muted"],
        }
        tier_color = evidence_colors.get(evidence, palette["muted"])

        st.markdown(
            f"""
            <div class="gw-stat-row">
                <span class="gw-badge" style="background:{tier_color};">{evidence} evidence</span>
                <span class="gw-stat">⏱ {entry.get('elapsed', 0):.1f}s</span>
                <span class="gw-stat">📚 {len(sources)} relevant source(s) found</span>
                <span class="gw-stat">🎯 top score {top_score:.3f}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            "<div style='margin:14px 0 2px 0;font-weight:700;font-size:0.95rem;"
            f"color:{palette['text']};'>📚 Sources</div>",
            unsafe_allow_html=True,
        )

        if not sources:
            st.info("No sources returned.")
        elif not filtered:
            st.warning(f"All {len(sources)} source(s) scored below your {score_threshold:.2f} threshold. "
                       "Lower it in the sidebar to see them.")
        else:
            search_term = st.text_input(
                "🔎 Search within these sources",
                key=f"src_search_{msg_idx}",
                placeholder="e.g. insurance, termination, liability — highlights matches below",
            ).strip()

            overlap_terms = extract_overlap_terms(entry["question"], entry["answer"])

            # Target language for the optional per-source excerpt translation:
            # the explicit sidebar choice, or (if "auto") whatever this answer
            # was actually given in. None/"en" means there's nothing useful to
            # translate to, so the toggle won't be shown at all.
            excerpt_target_lang = language_code if language_code != "auto" else entry.get("detected_language")

            _last_filename = None
            for i, source in enumerate(filtered, start=1):
                if source["filename"] != _last_filename:
                    _last_filename = source["filename"]
                    st.markdown(
                        f"<div style='margin:16px 0 4px 0;font-weight:700;font-size:0.85rem;"
                        f"color:{palette['accent']};'>📄 {source['filename']}</div>",
                        unsafe_allow_html=True,
                    )
                points = split_into_points(source["text"])
                cited_flags = [point_is_cited(p, quotes) for p in points]
                cited_count = sum(cited_flags)
                strength_pct = max(0, min(100, round(source["score"] * 100)))

                with st.container(border=True):
                    head_l, head_r = st.columns([3, 1])
                    with head_l:
                        st.markdown(f"**{i}. {source['filename']}**")
                        cite_note = f" · ✓ {cited_count} point(s) cited in the answer" if cited_count else ""
                        st.caption(f"chunk {source['chunk_index']}{cite_note}")
                    with head_r:
                        st.markdown(
                            f"""
                            <div style="text-align:right;font-size:0.78rem;color:{palette['muted']};">score {source['score']:.3f}</div>
                            <div style="background:{palette['border']};border-radius:999px;height:6px;margin-top:4px;">
                                <div style="background:{palette['accent']};width:{strength_pct}%;height:6px;border-radius:999px;"></div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    def render_point(p: str, cited: bool):
                        # Verbatim text is only ever escaped and marked up for
                        # display (bold/highlight) — the words themselves are
                        # never changed, reworded, or reordered.
                        esc = html.escape(p)
                        esc = bold_overlap_html(esc, overlap_terms)
                        esc = highlight_html(esc, search_term, palette["warn"] + "66")
                        if cited:
                            st.markdown(
                                f"<div style='background:{palette['accent_soft']};border-left:3px solid {palette['accent']};"
                                f"padding:6px 10px;margin:4px 0;border-radius:6px;font-size:0.85rem;color:{palette['text']};'>"
                                f"✓ <b>cited in answer</b> — {esc}</div>",
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown(
                                f"<div style='padding:4px 10px;margin:2px 0;font-size:0.85rem;color:{palette['muted']};'>• {esc}</div>",
                                unsafe_allow_html=True,
                            )

                    shown = points[:POINTS_SHOWN_BY_DEFAULT]
                    shown_flags = cited_flags[:POINTS_SHOWN_BY_DEFAULT]
                    for p, cited in zip(shown, shown_flags):
                        render_point(p, cited)

                    rest = points[POINTS_SHOWN_BY_DEFAULT:]
                    rest_flags = cited_flags[POINTS_SHOWN_BY_DEFAULT:]
                    if rest:
                        with st.expander(f"📖 Show {len(rest)} more point(s)"):
                            for p, cited in zip(rest, rest_flags):
                                render_point(p, cited)

                    # Always one click away, separate from the readable points
                    # above — this is the unedited chunk exactly as retrieved,
                    # never a rewrite.
                    with st.expander("Show original text"):
                        st.caption("Verbatim chunk, exactly as retrieved — no splitting, bolding, or rewording.")
                        st.code(source["text"], language=None, wrap_lines=True)

                        if excerpt_target_lang and excerpt_target_lang != "en":
                            target_name = LANGUAGE_NAMES_BY_CODE.get(excerpt_target_lang, excerpt_target_lang)
                            if st.checkbox(
                                f"🌐 Translate excerpt to {target_name} (machine translation, not legally authoritative)",
                                key=f"xlate_toggle_{msg_idx}_{i}",
                            ):
                                cache_key = f"xlate_text_{msg_idx}_{i}_{excerpt_target_lang}"
                                if cache_key not in st.session_state:
                                    try:
                                        with st.spinner("Translating excerpt…"):
                                            tr = requests.post(
                                                f"{API_URL}/translate",
                                                json={"text": source["text"], "target_language": excerpt_target_lang},
                                                headers=auth_headers(),
                                                timeout=60,
                                            )
                                        tr.raise_for_status()
                                        translated = tr.json().get("translated_text", "")
                                        st.session_state[cache_key] = translated or None
                                        if not translated:
                                            st.warning("Translation returned an empty result.")
                                    except requests.exceptions.ConnectionError:
                                        st.session_state[cache_key] = None
                                        st.error("Could not connect to the backend to translate this excerpt.")
                                    except requests.exceptions.Timeout:
                                        st.session_state[cache_key] = None
                                        st.error("Translating this excerpt timed out.")
                                    except requests.RequestException as e:
                                        st.session_state[cache_key] = None
                                        detail = ""
                                        try:
                                            detail = tr.json().get("detail", "")
                                        except Exception:
                                            pass
                                        st.error(f"Translation failed: {detail or e}")

                                cached = st.session_state.get(cache_key)
                                if cached:
                                    st.markdown(f"🌐 **Machine translation ({target_name}) — not legally authoritative**")
                                    st.markdown(cached)

# ---------------- Chat input ----------------
if prompt := st.chat_input("Ask about the indexed contracts…"):
    run_query(prompt, top_k, language_code)
    st.rerun()
