import requests
import streamlit as st

API_BASE = "http://0.0.0.0:8000"

EXAMPLE_QUESTIONS = [
    "Is water damage from frozen pipes covered if vacant 65 days?",
    "Does endorsement NX-END-02 override Section 7.3?",
    "What is the hurricane deductible for Florida properties?",
    "What endorsements are attached to John Smith policy?",
]

st.set_page_config(
    page_title="Insurance Policy Assistant",
    page_icon="📋",
    layout="wide",
)

# Session state initialised once — persists across reruns within the session.
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_query" not in st.session_state:
    st.session_state.pending_query = None


def check_health() -> bool:
    try:
        r = requests.get(f"{API_BASE}/health", timeout=3)
        return r.status_code == 200
    except requests.exceptions.ConnectionError:
        return False


def call_ingest() -> dict:
    r = requests.post(f"{API_BASE}/ingest", timeout=300)
    r.raise_for_status()
    return r.json()


def call_query(query: str) -> dict:
    r = requests.post(f"{API_BASE}/query", json={"query": query}, timeout=60)
    r.raise_for_status()
    return r.json()


def render_sources(response: dict) -> None:
    sources        = response.get("sources", [])
    citation_check = response.get("citation_check", {})

    with st.expander("Sources & Citations"):
        if sources:
            for src in sources:
                st.markdown(
                    f"📄 **{src.get('source', 'unknown')}** | "
                    f"Page {src.get('page', '?')} | "
                    f"Section: {src.get('section', 'unknown')} | "
                    f"Type: {src.get('doc_type', 'unknown')}"
                )
        else:
            st.caption("No sources returned.")

        st.divider()
        hallucinated = citation_check.get("hallucinated_citations", [])
        if citation_check.get("is_clean", True):
            st.success("✓ All citations verified")
        else:
            st.warning(f"⚠ {len(hallucinated)} unverified citation(s): {', '.join(hallucinated)}")


def submit_query(query: str) -> None:
    st.session_state.messages.append({"role": "user", "content": query})
    with st.spinner("Thinking..."):
        try:
            response = call_query(query)
            answer   = response.get("answer", "No answer returned.")
            st.session_state.messages.append({
                "role":     "assistant",
                "content":  answer,
                "response": response,
            })
        except requests.exceptions.ConnectionError:
            st.session_state.messages.append({
                "role":    "assistant",
                "content": "⚠️ Cannot reach the API. Make sure the FastAPI server is running at " + API_BASE,
            })
        except requests.exceptions.HTTPError as e:
            detail = ""
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = str(e)
            st.session_state.messages.append({
                "role":    "assistant",
                "content": f"⚠️ API error: {detail}",
            })


# ── Left column ──────────────────────────────────────────────────────────────
left, right = st.columns([0.3, 0.7])

with left:
    st.title("📋 Insurance Policy Assistant")
    st.caption("Ask questions about insurance policies, coverage, exclusions, and deductibles.")

    st.divider()

    # API status checked on every page load — gives immediate feedback if the
    # backend is down before the user wastes a query attempt.
    api_online = check_health()
    if api_online:
        st.success("🟢 API Online")
    else:
        st.error("🔴 API Offline")

    st.divider()

    if st.button("Load Knowledge Base", use_container_width=True):
        with st.spinner("Ingesting documents..."):
            try:
                result = call_ingest()
                st.success(
                    f"✓ Loaded {result.get('total_chunks', '?')} chunks "
                    f"from {result.get('total_pdfs', '?')} PDFs."
                )
            except requests.exceptions.ConnectionError:
                st.error("Cannot reach the API. Is the server running?")
            except requests.exceptions.HTTPError as e:
                try:
                    detail = e.response.json().get("detail", str(e))
                except Exception:
                    detail = str(e)
                st.error(f"Ingestion failed: {detail}")

    st.divider()
    st.markdown("**Example Questions**")

    # Buttons write the query into pending_query then rerun — the chat area
    # picks it up and submits it, keeping the flow identical to manual typing.
    for question in EXAMPLE_QUESTIONS:
        if st.button(question, use_container_width=True):
            st.session_state.pending_query = question
            st.rerun()

# ── Right column ─────────────────────────────────────────────────────────────
with right:
    # Render full conversation history before the input box.
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and "response" in msg:
                render_sources(msg["response"])

    # Handle example-button queries that were set in the previous rerun.
    if st.session_state.pending_query:
        query = st.session_state.pending_query
        st.session_state.pending_query = None
        submit_query(query)
        st.rerun()

    if user_input := st.chat_input("Ask about coverage, exclusions, deductibles..."):
        submit_query(user_input)
        st.rerun()
