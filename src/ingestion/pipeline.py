import json
import os
import re
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from mistralai import Mistral
from pypdf import PdfReader

load_dotenv()

# ---------------------------------------------------------------------------
# Section header patterns for insurance legal documents
# ---------------------------------------------------------------------------
_SECTION_PATTERNS = [
    r"^SECTION\s+(I{1,4}|IV|V)\b",          # SECTION I, II, III, IV
    r"^Coverage\s+[A-F]\b",                  # Coverage A through F
    r"^\d+\.\d*\s+[A-Z]",                    # 7. or 7.3 followed by capital
    r"^[A-Z][A-Z\s]{4,}$",                   # all-caps lines: AGREEMENT, DEFINITIONS
]
_SECTION_RE = re.compile("|".join(_SECTION_PATTERNS), re.MULTILINE)

_MAX_CHUNK_CHARS = 2000   # ~500 tokens at ~4 chars/token
_OVERLAP_CHARS   = 300    # ~15% overlap to preserve cross-sentence context


def extract_text_from_pdf(pdf_path: Path) -> list[dict]:
    """Extract text page by page. Page numbers are kept so we can cite the
    source page when the retriever returns a chunk to the user."""
    reader = PdfReader(str(pdf_path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append({"page": i, "text": text})
    return pages


def detect_document_type(filename: str) -> str:
    """Tagging doc type at ingest time lets the retriever filter by category
    (e.g. only search endorsements) without re-reading file contents."""
    stem = Path(filename).stem.lower()
    if stem.startswith("base_policy") or stem.startswith("real_policy"):
        return "base_policy"
    if stem.startswith("endorsement"):
        return "endorsement"
    if stem.startswith("amendment"):
        return "amendment"
    if stem.startswith("declarations"):
        return "declarations"
    return "unknown"


def _split_with_overlap(text: str, max_chars: int, overlap: int) -> list[str]:
    """Fixed-size split with overlap so that sentences straddling a boundary
    appear in both adjacent chunks and are never silently dropped."""
    chunks, start = [], 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        start = end - overlap
    return [c for c in chunks if c.strip()]


def chunk_document(pages: list[dict], filename: str) -> list[dict]:
    """Section-aware chunking keeps legal cross-references intact. Splitting
    mid-clause (e.g. inside Section 7.3) would strip the section number from
    the surrounding text, making cosine retrieval miss it entirely."""
    doc_type = detect_document_type(filename)
    stem = Path(filename).stem

    # Merge all pages into one string; record where each page boundary falls.
    full_text = ""
    page_boundaries: list[tuple[int, int]] = []   # (char_offset, page_number)
    for p in pages:
        page_boundaries.append((len(full_text), p["page"]))
        full_text += p["text"] + "\n"

    def char_to_page(offset: int) -> int:
        page = page_boundaries[0][1]
        for char_off, pg in page_boundaries:
            if offset >= char_off:
                page = pg
        return page

    # Try to split on detected section headers first.
    matches = list(_SECTION_RE.finditer(full_text))
    if matches:
        boundaries = [m.start() for m in matches] + [len(full_text)]
        raw_sections: list[tuple[str, str]] = []
        for i, start in enumerate(boundaries[:-1]):
            header_match = matches[i]
            title = header_match.group().strip()
            body  = full_text[start:boundaries[i + 1]]
            raw_sections.append((title, body))
    else:
        # No headers found — treat the whole document as one unnamed section.
        raw_sections = [("unknown", full_text)]

    chunks: list[dict] = []
    for title, body in raw_sections:
        if len(body) > _MAX_CHUNK_CHARS:
            sub_texts = _split_with_overlap(body, _MAX_CHUNK_CHARS, _OVERLAP_CHARS)
        else:
            sub_texts = [body]

        for sub in sub_texts:
            if not sub.strip():
                continue
            idx = len(chunks)
            # Find approximately where in the original document this chunk starts.
            offset = full_text.find(sub[:50])
            chunks.append({
                "chunk_id":     f"{stem}_chunk_{idx}",
                "text":         sub.strip(),
                "source":       filename,
                "doc_type":     doc_type,
                "page_start":   char_to_page(max(offset, 0)),
                "section_title": title,
                "char_count":   len(sub.strip()),
            })

    return chunks


def embed_chunks(chunks: list[dict]) -> list[dict]:
    """Mistral's free tier enforces per-minute rate limits, so we batch to
    stay under the threshold and avoid 429 errors mid-ingestion."""
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    batch_size = 10
    embedded: list[dict] = []

    for batch_start in range(0, len(chunks), batch_size):
        batch = chunks[batch_start : batch_start + batch_size]
        texts = [c["text"] for c in batch]
        try:
            response = client.embeddings.create(model="mistral-embed", inputs=texts)
            for chunk, emb_obj in zip(batch, response.data):
                embedded.append({**chunk, "embedding": emb_obj.embedding})
        except Exception as exc:
            # Log and skip the whole batch rather than crashing the pipeline.
            for chunk in batch:
                print(f"[WARN] embedding failed for {chunk['chunk_id']}: {exc}")
        if batch_start + batch_size < len(chunks):
            time.sleep(1)

    return embedded


def save_to_vector_store(chunks: list[dict], store_dir: Path) -> None:
    """Vectors live in a numpy file for fast vectorised cosine ops; metadata
    stays in JSON so humans can inspect it and the retriever can filter
    without loading the full float matrix."""
    store_dir.mkdir(parents=True, exist_ok=True)

    embeddings = np.array([c["embedding"] for c in chunks], dtype=np.float32)
    np.save(store_dir / "embeddings.npy", embeddings)

    metadata = [{k: v for k, v in c.items() if k != "embedding"} for c in chunks]
    (store_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )


def load_vector_store(store_dir: Path) -> tuple[np.ndarray, list[dict]]:
    """Called at query time, not during ingestion. Loads the pre-built index
    from disk so the API server doesn't need to re-embed anything on startup."""
    embeddings = np.load(store_dir / "embeddings.npy")
    metadata   = json.loads((store_dir / "metadata.json").read_text(encoding="utf-8"))
    return embeddings, metadata


def ingest_pdfs(pdf_paths: list[Path], store_dir: Path) -> dict:
    """Full pipeline: extract → chunk across all PDFs, then embed in one
    batched pass, then persist. Embedding all chunks together maximises batch
    efficiency and keeps API calls predictable."""
    all_chunks: list[dict] = []

    for pdf_path in pdf_paths:
        pages  = extract_text_from_pdf(pdf_path)
        chunks = chunk_document(pages, pdf_path.name)
        all_chunks.extend(chunks)

    embedded = embed_chunks(all_chunks)
    save_to_vector_store(embedded, store_dir)

    return {
        "total_pdfs":   len(pdf_paths),
        "total_chunks": len(embedded),
        "store_dir":    str(store_dir),
    }
