import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from src.ingestion.pipeline import ingest_pdfs

load_dotenv()

VECTOR_STORE_DIR = Path("vector_store")
DOCS_DIR         = Path("data/raw_docs")
TEMP_DIR         = Path("temp")

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB in bytes

app = FastAPI(
    title="Insurance RAG API",
    description="RAG pipeline for insurance policy document Q&A",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
