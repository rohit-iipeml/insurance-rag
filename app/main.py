import asyncio
import json
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
)
from src.ingestion.pipeline import ingest_pdfs, load_bm25_index, load_vector_store
from src.retrieval.pipeline import is_conversational, is_pii_query, merge_subquery_results, rerank_chunks, retrieve

load_dotenv()

VECTOR_STORE_DIR = Path("vector_store")
DOCS_DIR         = Path("data/raw_docs")
TEMP_DIR         = Path("temp")

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB in bytes

_REFUSAL_INTENTS = {"pii_sensitive", "legal_advice", "out_of_scope"}


class QueryRequest(BaseModel):
    query: str
    jurisdiction: str | None = None  # optional state filter e.g. 'CA', 'TX'
    chat_history: list[dict] | None = None


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
    yield
    # Nothing to clean up — numpy arrays are garbage collected automatically


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
        result = retrieve(
            query_embedding      = query_embedding,
            query_text           = sub["query"],
            embeddings_matrix    = app_state.embeddings,
            metadata             = app_state.metadata,
            bm25_index           = app_state.bm25_index,
            doc_type_filter      = sub.get("doc_type"),
            jurisdiction_filter  = effective_jurisdiction,
        )
        subquery_results.append(result)

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
        merged = await _run_retrieval(sub_queries, rewritten_q, effective_jurisdiction, app.state)
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

        merged = await _run_retrieval(sub_queries, rewritten_q, effective_jurisdiction, app.state)

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

                loop = asyncio.get_event_loop()
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
                while True:
                    token = await queue.get()
                    if token is None:
                        if pending:
                            yield f"data: {json.dumps(pending)}\n\n"
                        yield "data: [DONE]\n\n"
                        sources_data = format_sources(merged["chunks"])
                        meta_event = json.dumps({
                            "sources": sources_data,
                            "citation_check": {"verified_citations": [], "hallucinated_citations": [], "is_clean": True},
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
