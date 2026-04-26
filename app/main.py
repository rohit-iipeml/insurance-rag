import asyncio
import json
import os
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from mistralai import Mistral
from pydantic import BaseModel

from src.generation.pipeline import (
    GENERATION_MODEL,
    _mistral_with_retry,
    build_generation_messages,
    detect_intent_and_decompose,
    format_sources,
    rewrite_query_with_history,
    run_generation_pipeline,
    verify_citations,
)
from src.ingestion.pipeline import (
    ingest_pdfs,
    load_bm25_index,
    load_vector_store,
    extract_text_from_pdf,
    chunk_document,
    embed_chunks,
    build_bm25_plus_index,
)
from src.retrieval.pipeline import is_conversational, is_pii_query, merge_subquery_results, rerank_chunks, retrieve

load_dotenv()

VECTOR_STORE_DIR  = Path("vector_store")
DOCS_DIR          = Path("data/raw_docs")
TEMP_DIR          = Path("temp")
SESSION_DOCS_DIR  = Path("data/session_docs")

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB in bytes

_REFUSAL_INTENTS = {"pii_sensitive", "legal_advice", "out_of_scope"}


class SessionManager:
    def __init__(self):
        self.active_sessions: dict = {}

    def get_session(self, session_id: str) -> dict | None:
        session = self.active_sessions.get(session_id)
        if session:
            session["last_active"] = time.time()
        return session

    def create_or_update(
        self,
        session_id: str,
        embeddings: np.ndarray,
        metadata: list,
        bm25_index: dict,
        files: dict,
    ) -> None:
        if session_id not in self.active_sessions:
            self.active_sessions[session_id] = {
                "embeddings":  embeddings,
                "metadata":    metadata,
                "bm25_index":  bm25_index,
                "files":       files,
                "last_active": time.time(),
            }
        else:
            existing = self.active_sessions[session_id]
            existing["embeddings"] = np.vstack([existing["embeddings"], embeddings])
            existing["metadata"].extend(metadata)
            existing["bm25_index"] = build_bm25_plus_index(existing["metadata"])
            existing["files"].update(files)
            existing["last_active"] = time.time()

    def cleanup(self, max_age_seconds: int = 7200) -> None:
        now = time.time()
        to_delete = [
            sid for sid, data in self.active_sessions.items()
            if now - data["last_active"] > max_age_seconds
        ]
        for sid in to_delete:
            shutil.rmtree(SESSION_DOCS_DIR / sid, ignore_errors=True)
            del self.active_sessions[sid]


class QueryRequest(BaseModel):
    query: str
    jurisdiction: str | None = None  # optional state filter e.g. 'CA', 'TX'
    chat_history: list[dict] | None = None
    session_id: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load vector store and BM25 index once at startup — reloading per query
    # would add 50-150ms disk I/O overhead with no benefit at this corpus size.
    # Both are read-only after loading so concurrent queries are safe.
    if VECTOR_STORE_DIR.exists() and (VECTOR_STORE_DIR / "embeddings.npy").exists():
        app.state.embeddings, app.state.metadata = load_vector_store(VECTOR_STORE_DIR)
        app.state.bm25_index  = load_bm25_index(VECTOR_STORE_DIR)
        app.state.index_loaded = True
    else:
        app.state.index_loaded = False

    app.state.session_manager = SessionManager()

    async def _cleanup_loop():
        while True:
            await asyncio.sleep(3600)
            app.state.session_manager.cleanup()

    cleanup_task = asyncio.create_task(_cleanup_loop())
    yield
    cleanup_task.cancel()


app = FastAPI(
    title="Insurance RAG API",
    description="RAG pipeline for insurance policy document Q&A",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok", "message": "Insurance RAG API is running"}


@app.post("/ingest")
async def ingest(files: list[UploadFile] = File(default=[])) -> dict:
    try:
        if files:
            saved_paths = _save_uploads(files)
            # finally ensures temp files are removed even if ingest_pdfs raises
            # partway through — leaving gigabytes of PDFs in /temp on a crash
            # would silently fill disk on repeated calls.
            try:
                result = ingest_pdfs(saved_paths, VECTOR_STORE_DIR)
            finally:
                shutil.rmtree(TEMP_DIR, ignore_errors=True)
        else:
            pdf_paths = list(DOCS_DIR.glob("*.pdf"))
            if not pdf_paths:
                raise HTTPException(
                    status_code=404,
                    detail="No PDFs found in data/raw_docs/",
                )
            result = ingest_pdfs(pdf_paths, VECTOR_STORE_DIR)

        # Reload index into memory after ingestion so queries use fresh data
        # without requiring a server restart.
        app.state.embeddings, app.state.metadata = load_vector_store(VECTOR_STORE_DIR)
        app.state.bm25_index  = load_bm25_index(VECTOR_STORE_DIR)
        app.state.index_loaded = True

        return {
            "status":            "success",
            "total_pdfs":        result["total_pdfs"],
            "total_chunks":      result["total_chunks"],
            "bm25_unique_terms": result["bm25_unique_terms"],
            "message":           f"Ingested {result['total_pdfs']} PDF(s) into {result['total_chunks']} chunks.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _run_retrieval(
    sub_queries: list[dict],
    rewritten_q: str,
    effective_jurisdiction: str | None,
    app_state,
    session_data: dict | None = None,
) -> dict:
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    subquery_results: list[dict] = []

    for sub in sub_queries:
        embed_response = _mistral_with_retry(
            lambda s=sub: client.embeddings.create(
                model="mistral-embed",
                inputs=[s["query"]],
            )
        )
        query_embedding = np.array(embed_response.data[0].embedding, dtype=np.float32)

        global_result = retrieve(
            query_embedding     = query_embedding,
            query_text          = sub["query"],
            embeddings_matrix   = app_state.embeddings,
            metadata            = app_state.metadata,
            bm25_index          = app_state.bm25_index,
            doc_type_filter     = sub.get("doc_type"),
            jurisdiction_filter = effective_jurisdiction,
        )
        subquery_results.append(global_result)

        if session_data and len(session_data.get("metadata", [])) > 0:
            session_result = retrieve(
                query_embedding     = query_embedding,
                query_text          = sub["query"],
                embeddings_matrix   = session_data["embeddings"],
                metadata            = session_data["metadata"],
                bm25_index          = session_data["bm25_index"],
                doc_type_filter     = None,
                jurisdiction_filter = None,
            )
            subquery_results.append(session_result)

    merged = merge_subquery_results(subquery_results)
    if merged["sufficient_evidence"]:
        merged["chunks"] = await rerank_chunks(
            query   = rewritten_q,
            chunks  = merged["chunks"],
            api_key = os.environ["MISTRAL_API_KEY"],
        )
    return merged


@app.post("/query")
async def query(request: QueryRequest) -> dict:
    try:
        if not app.state.index_loaded:
            raise HTTPException(
                status_code=503,
                detail="Knowledge base not loaded. Please call POST /ingest first.",
            )

        q = request.query

        if is_pii_query(q):
            return {
                "answer":          "This query contains sensitive personal information and cannot be processed.",
                "sources":         [],
                "intent":          "pii_sensitive",
                "citation_check":  {"verified_citations": [], "hallucinated_citations": [], "is_clean": True},
                "answer_template": None,
            }

        if is_conversational(q):
            return {
                "answer":          "I am an insurance policy assistant. Ask me about coverage, exclusions, deductibles, or policy terms.",
                "sources":         [],
                "intent":          "conversational",
                "citation_check":  {"verified_citations": [], "hallucinated_citations": [], "is_clean": True},
                "answer_template": None,
            }

        rewritten_q = rewrite_query_with_history(q, request.chat_history or [])
        print(f"[REWRITE] {q!r} -> {rewritten_q!r}")

        analysis = detect_intent_and_decompose(rewritten_q)
        intent                 = analysis.get("intent", "retrieval")
        sub_queries            = analysis.get("sub_queries", [{"query": rewritten_q, "doc_type": None}])
        answer_template        = analysis.get("answer_template", "general")
        refusal_reason         = analysis.get("refusal_reason")
        effective_jurisdiction = request.jurisdiction or analysis.get("jurisdiction")

        if intent in _REFUSAL_INTENTS:
            return {
                "answer":          refusal_reason,
                "sources":         [],
                "intent":          intent,
                "citation_check":  {"verified_citations": [], "hallucinated_citations": [], "is_clean": True},
                "answer_template": None,
            }

        # Embed and retrieve each sub-query independently — routing by doc_type
        # lets each sub-query target the document category most likely to hold
        # its answer, reducing noise in the merged context window.
        session_data = None
        if request.session_id:
            session_data = app.state.session_manager.get_session(request.session_id)

        merged = await _run_retrieval(sub_queries, rewritten_q, effective_jurisdiction, app.state, session_data)
        generation = run_generation_pipeline(
            query               = rewritten_q,
            chunks              = merged["chunks"],
            answer_template     = answer_template,
            sufficient_evidence = merged["sufficient_evidence"],
            chat_history        = request.chat_history,
        )

        return {
            "answer":           generation["answer"],
            "sources":          generation["sources"],
            "citation_check":   generation["citation_check"],
            "intent":           intent,
            "answer_template":  answer_template,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/query/stream")
async def query_stream(request: QueryRequest):
    """Same pipeline as /query but streams generation tokens via SSE.
    Sources and citation check are not available in streaming mode."""
    try:
        if not app.state.index_loaded:
            raise HTTPException(
                status_code=503,
                detail="Knowledge base not loaded. Please call POST /ingest first.",
            )

        q = request.query

        if is_pii_query(q):
            async def _pii():
                yield "data: This query contains sensitive personal information and cannot be processed.\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(
                _pii(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*"},
            )

        if is_conversational(q):
            async def _conv():
                yield "data: I am an insurance policy assistant. Ask me about coverage, exclusions, deductibles, or policy terms.\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(
                _conv(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*"},
            )

        rewritten_q = rewrite_query_with_history(q, request.chat_history or [])
        print(f"[REWRITE] {q!r} -> {rewritten_q!r}")

        analysis               = detect_intent_and_decompose(rewritten_q)
        intent                 = analysis.get("intent", "retrieval")
        sub_queries            = analysis.get("sub_queries", [{"query": rewritten_q, "doc_type": None}])
        answer_template        = analysis.get("answer_template", "general")
        refusal_reason         = analysis.get("refusal_reason")
        effective_jurisdiction = request.jurisdiction or analysis.get("jurisdiction")

        if intent in _REFUSAL_INTENTS:
            async def _refusal():
                yield f"data: {refusal_reason}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(
                _refusal(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*"},
            )

        session_data = None
        if request.session_id:
            session_data = app.state.session_manager.get_session(request.session_id)

        merged = await _run_retrieval(sub_queries, rewritten_q, effective_jurisdiction, app.state, session_data)
        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

        if not merged["sufficient_evidence"]:
            from src.generation.pipeline import INSUFFICIENT_EVIDENCE_MSG
            async def _insufficient():
                yield f"data: {INSUFFICIENT_EVIDENCE_MSG}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(
                _insufficient(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*"},
            )

        messages = build_generation_messages(rewritten_q, merged["chunks"], answer_template, chat_history=request.chat_history)

        async def token_generator():
            try:
                def stream_tokens(messages, model):
                    with client.chat.stream(
                        model=model,
                        messages=messages,
                    ) as stream:
                        for chunk in stream:
                            content = chunk.data.choices[0].delta.content
                            if content:
                                yield content

                loop = asyncio.get_running_loop()
                queue = asyncio.Queue()

                def run_stream():
                    try:
                        for token in stream_tokens(messages, GENERATION_MODEL):
                            asyncio.run_coroutine_threadsafe(queue.put(token), loop)
                        asyncio.run_coroutine_threadsafe(queue.put(None), loop)
                    except Exception as e:
                        asyncio.run_coroutine_threadsafe(queue.put(f"[ERROR] {e}"), loop)

                import threading
                threading.Thread(target=run_stream, daemon=True).start()

                pending = ""
                full_answer = ""
                while True:
                    token = await queue.get()
                    if token is None:
                        if pending:
                            full_answer += pending
                            yield f"data: {json.dumps(pending)}\n\n"
                        yield "data: [DONE]\n\n"
                        citation_check = verify_citations(full_answer, merged["chunks"])
                        cited_indices = {int(n) - 1 for n in citation_check["verified_citations"] if n.isdigit()}
                        cited_chunks = [merged["chunks"][i] for i in sorted(cited_indices) if i < len(merged["chunks"])]
                        sources_data = format_sources(cited_chunks if cited_chunks else merged["chunks"])
                        meta_event = json.dumps({
                            "sources": sources_data,
                            "citation_check": citation_check,
                        })
                        yield f"data: [SOURCES]{meta_event}\n\n"
                        break
                    elif isinstance(token, str) and token.startswith("[ERROR]"):
                        if pending:
                            yield f"data: {json.dumps(pending)}\n\n"
                        yield f"data: {token}\n\n"
                        break
                    else:
                        pending += token
                        full_answer += token
                        open_pos = pending.rfind("[")
                        if open_pos != -1 and "]" not in pending[open_pos:]:
                            if len(pending) - open_pos > 10:
                                yield f"data: {json.dumps(pending)}\n\n"
                                pending = ""
                            continue
                        yield f"data: {json.dumps(pending)}\n\n"
                        pending = ""
            except Exception as e:
                yield f"data: [ERROR] {e}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            token_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Access-Control-Allow-Origin": "*"},
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _save_uploads(files: list[UploadFile]) -> list[Path]:
    """Validate and persist uploaded files to TEMP_DIR, returning their paths."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    for upload in files:
        if not (upload.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are accepted")

        content = upload.file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File exceeds 50MB limit")

        dest = TEMP_DIR / Path(upload.filename).name
        dest.write_bytes(content)
        saved.append(dest)

    return saved


@app.post("/session/ingest")
async def session_ingest(
    session_id: str = Form(...),
    files: list[UploadFile] = File(...),
) -> dict:
    try:
        if not files:
            raise HTTPException(status_code=400, detail="No files provided.")

        session_dir = SESSION_DOCS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        saved_paths: list[Path] = []
        saved_files: dict = {}

        for upload in files:
            if not (upload.filename or "").lower().endswith(".pdf"):
                raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
            content = await upload.read()
            if len(content) > MAX_FILE_SIZE:
                raise HTTPException(status_code=400, detail="File exceeds 50MB limit.")
            safe_name = Path(upload.filename).name
            dest = session_dir / safe_name
            dest.write_bytes(content)
            saved_paths.append(dest)
            saved_files[safe_name] = str(dest)

        all_chunks: list[dict] = []
        for pdf_path in saved_paths:
            pages  = extract_text_from_pdf(pdf_path)
            chunks = chunk_document(pages, pdf_path.name)
            all_chunks.extend(chunks)

        if not all_chunks:
            raise HTTPException(status_code=400, detail="No text could be extracted from the uploaded PDFs.")

        embedded = embed_chunks(all_chunks)
        if not embedded:
            raise HTTPException(status_code=500, detail="Embedding failed for all chunks.")

        embeddings_array = np.array([c["embedding"] for c in embedded], dtype=np.float32)
        metadata_list    = [{**{k: v for k, v in c.items() if k != "embedding"}, "is_session": True} for c in embedded]
        bm25_index       = build_bm25_plus_index(embedded)

        app.state.session_manager.create_or_update(
            session_id = session_id,
            embeddings = embeddings_array,
            metadata   = metadata_list,
            bm25_index = bm25_index,
            files      = saved_files,
        )

        return {
            "status":       "success",
            "session_id":   session_id,
            "total_pdfs":   len(saved_paths),
            "total_chunks": len(embedded),
            "message":      f"Ingested {len(saved_paths)} PDF(s) into {len(embedded)} session chunks.",
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pdf/global/{filename}")
async def get_global_pdf(filename: str):
    safe_name = Path(filename).name
    file_path = DOCS_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        str(file_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={safe_name}"},
    )


@app.get("/pdf/{session_id}/{filename}")
async def get_session_pdf(session_id: str, filename: str):
    safe_name = Path(filename).name
    file_path = SESSION_DOCS_DIR / session_id / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        str(file_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={safe_name}"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
