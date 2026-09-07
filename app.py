import requests
import streamlit as st

API_URL = "http://localhost:8000"

st.set_page_config(
    page_title="Groundwork — Contract Assistant",
    page_icon="📄",
    layout="wide",
)

st.title("📄 Groundwork — Contract Intelligence")
st.caption("Ask questions about the indexed contract documents.")

# Sidebar
with st.sidebar:
    st.header("Settings")
    top_k = st.slider(
        "Number of sources",
        min_value=1,
        max_value=10,
        value=5,
    )

    st.divider()

    st.markdown("### Backend")
    try:
        health = requests.get(f"{API_URL}/health", timeout=5)
        if health.ok:
            st.success("API is online")
            provider = health.json().get("llm_provider", "unknown")
            st.caption(f"LLM provider: {provider}")
        else:
            st.error("API returned an error")
    except requests.RequestException:
        st.error("API is offline")
        st.caption("Start the FastAPI server on port 8000.")

question = st.text_area(
    "Your contract question",
    placeholder="Example: Can we claim EOT for delayed work?",
    height=120,
)

if st.button("🔍 Ask", type="primary"):
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

                st.subheader("Answer")
                st.write(result.get("answer", "No answer returned."))

                sources = result.get("sources", [])

                st.subheader("Sources")
                if not sources:
                    st.info("No sources returned.")
                else:
                    for i, source in enumerate(sources, start=1):
                        with st.expander(
                            f"{i}. {source['filename']} — "
                            f"chunk {source['chunk_index']} "
                            f"(score: {source['score']:.3f})"
                        ):
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