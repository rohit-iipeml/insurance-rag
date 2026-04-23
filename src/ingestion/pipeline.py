import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from mistralai import Mistral
from pypdf import PdfReader

load_dotenv()

# Section header patterns for insurance legal documents

_SECTION_PATTERNS = [
    r"^\s*SECTION\s+(I{1,4}|IV|V|VI|VII|VIII|IX|X)\b",  # SECTION I–X, tolerates leading whitespace from PDF
    r"^\s*Coverage\s+[A-F]\b",                           # Coverage A through F
    r"^\d+\.\d*\s+[A-Z]",                                # 7. or 7.3 followed by capital
    r"^[A-Z][A-Z\s]{4,}$",                               # all-caps lines: AGREEMENT, DEFINITIONS
]
_SECTION_RE = re.compile("|".join(_SECTION_PATTERNS), re.MULTILINE | re.IGNORECASE)

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


def detect_jurisdiction(filename: str) -> str:
    """State code is stored per-chunk so the retriever can scope a query to
    a single state amendment without scanning unrelated documents."""
    stem = Path(filename).stem.lower()
    if stem.startswith("amendment_"):
        code = stem.split("_")[1].upper()
        if code in {"CA", "TX", "NY", "FL"}:
            return code
    return "all"


def extract_cross_references(text: str) -> list[str]:
    """Cross-references tie chunks to the clauses they modify; storing them in
    metadata lets the retriever surface related chunks without a second pass."""
    patterns = [
        r"Section\s+\d+\.\d+",          # Section 7.3
        r"Section\s+(?:I{1,4}|IV|V)\b", # Section I, II, III, IV
        r"NX-END-\d{2}",                 # NX-END-01 … NX-END-99
        r"NX-(?:HO|CP)-\d+",            # NX-HO-3, NX-CP-1, NX-HO-4
    ]
    found: list[str] = []
    for pattern in patterns:
        found.extend(re.findall(pattern, text))
    return list(dict.fromkeys(found))  # deduplicate while preserving order


def _split_with_overlap(text: str, max_chars: int, overlap: int) -> list[str]:
    """Fixed-size split with overlap so that sentences straddling a boundary
    appear in both adjacent chunks and are never silently dropped."""
    chunks, start = [], 0
    while start < len(text):
        end = start + max_chars
        if end < len(text):
            # walk back to nearest word boundary to avoid splitting mid-word
            while end > start and text[end] != ' ':
                end -= 1
            if end == start:
                end = start + max_chars  # no space found, fall back to hard cut
        chunks.append(text[start:end])
        start = end - overlap
    return [c for c in chunks if c.strip()]


def chunk_document(pages: list[dict], filename: str) -> list[dict]:
    """Section-aware chunking keeps legal cross-references intact. Splitting
    mid-clause (e.g. inside Section 7.3) would strip the section number from
    the surrounding text, making cosine retrieval miss it entirely."""
    doc_type     = detect_document_type(filename)
    jurisdiction = detect_jurisdiction(filename)
    stem         = Path(filename).stem

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
        # Preserve text before the first header (title, AGREEMENT, etc.) so it
        # isn't silently dropped from the index.
        if matches[0].start() > 0:
            raw_sections.append(("PREAMBLE", full_text[:matches[0].start()]))
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
                "chunk_id":       f"{stem}_chunk_{idx}",
                "text":           sub.strip(),
                "source":         filename,
                "doc_type":       doc_type,
                "jurisdiction":   jurisdiction,
                "page_start":     char_to_page(max(offset, 0)),
                "section_title":  title,
                "related_sections": extract_cross_references(sub),
                "char_count":     len(sub.strip()),
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
            # 429 rate-limit errors are transient; one retry after a longer
            # sleep recovers most failures without adding complex backoff logic.
            time.sleep(5)
            try:
                response = client.embeddings.create(model="mistral-embed", inputs=texts)
                for chunk, emb_obj in zip(batch, response.data):
                    embedded.append({**chunk, "embedding": emb_obj.embedding})
            except Exception as exc2:
                for chunk in batch:
                    print(f"[WARN] embedding failed for {chunk['chunk_id']}: {exc2}")
        if batch_start + batch_size < len(chunks):
            time.sleep(1)

    return embedded


def save_to_vector_store(chunks: list[dict], store_dir: Path) -> None:
    """Vectors live in a numpy file for fast vectorised cosine ops; metadata
    stays in JSON so humans can inspect it and the retriever can filter
    without loading the full float matrix."""
    if not chunks:
        raise ValueError(
            "No chunks were successfully embedded — nothing to save. "
            "Check your MISTRAL_API_KEY and retry."
        )

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
    # allow_pickle=False prevents arbitrary code execution from malicious .npy files
    embeddings = np.load(store_dir / "embeddings.npy", allow_pickle=False)
    metadata   = json.loads((store_dir / "metadata.json").read_text(encoding="utf-8"))
    return embeddings, metadata


def tokenize(text: str) -> list[str]:
    # Dots and hyphens are kept so legal identifiers like 'Section 7.3' and
    # 'NX-END-02' survive tokenization intact — splitting on them would destroy
    # the exact-match advantage BM25+ provides over semantic search.
    cleaned = re.sub(r"[^a-z0-9.\-\s]", "", text.lower())
    return [t for t in cleaned.split() if t]


def build_bm25_plus_index(chunks: list[dict]) -> dict:
    # BM25+ chosen over standard BM25 because our corpus has documents of very
    # different lengths (base policies ~1000 tokens vs endorsements ~300 tokens).
    # Standard BM25 would unfairly penalise long base-policy chunks that contain
    # a searched term. BM25+ adds delta=1.0 to the TF component to fix this.
    # BM25L was considered but rejected — it is designed for whole-document
    # retrieval over very long documents, not for pre-chunked corpora like ours.
    k1, b, delta = 1.5, 0.75, 1.0

    tokens_per_chunk  = [tokenize(c["text"]) for c in chunks]
    chunk_lengths     = [len(t) for t in tokens_per_chunk]
    avg_chunk_length  = sum(chunk_lengths) / len(chunk_lengths) if chunk_lengths else 1.0
    tf_per_chunk      = [dict(Counter(tokens)) for tokens in tokens_per_chunk]

    doc_freqs: dict[str, int] = {}
    for tf in tf_per_chunk:
        for term in tf:
            doc_freqs[term] = doc_freqs.get(term, 0) + 1

    return {
        "doc_freqs":        doc_freqs,
        "tf_per_chunk":     tf_per_chunk,
        "chunk_lengths":    chunk_lengths,
        "avg_chunk_length": avg_chunk_length,
        "total_chunks":     len(chunks),
        "chunk_ids":        [c["chunk_id"] for c in chunks],
        "k1":               k1,
        "b":                b,
        "delta":            delta,
    }


def bm25_plus_score(query: str, bm25_index: dict) -> list[tuple[int, float]]:
    # Only chunks with score > 0 are returned — a chunk scores 0 if it shares
    # no terms with the query, meaning it contributes only noise to RRF fusion.
    N           = bm25_index["total_chunks"]
    doc_freqs   = bm25_index["doc_freqs"]
    tf_per_chunk = bm25_index["tf_per_chunk"]
    chunk_lengths = bm25_index["chunk_lengths"]
    avg_len     = bm25_index["avg_chunk_length"]
    k1          = bm25_index["k1"]
    b           = bm25_index["b"]
    delta       = bm25_index["delta"]

    query_terms = tokenize(query)
    scores: list[float] = [0.0] * N

    for term in query_terms:
        df  = doc_freqs.get(term, 0)
        if df == 0:
            continue
        idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
        for i, tf in enumerate(tf_per_chunk):
            tf_td = tf.get(term, 0)
            if tf_td == 0:
                continue
            norm = k1 * (1 - b + b * chunk_lengths[i] / avg_len)
            tf_norm = delta + (tf_td * (k1 + 1)) / (tf_td + norm)
            scores[i] += idf * tf_norm

    return sorted(
        [(i, s) for i, s in enumerate(scores) if s > 0],
        key=lambda x: x[1],
        reverse=True,
    )


def save_bm25_index(bm25_index: dict, store_dir: Path) -> None:
    # Saved separately from embeddings.npy so the keyword index can be
    # inspected and debugged without loading the float matrix.
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / "bm25_index.json").write_text(
        json.dumps(bm25_index, indent=2), encoding="utf-8"
    )


def load_bm25_index(store_dir: Path) -> dict:
    # Loaded once at query time and kept in memory — the index is a plain
    # dict so no special deserialisation is needed.
    return json.loads((store_dir / "bm25_index.json").read_text(encoding="utf-8"))


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
    dropped = len(all_chunks) - len(embedded)
    if dropped > 0:
        print(f"[WARN] {dropped} chunks failed embedding and were excluded from the index.")
    save_to_vector_store(embedded, store_dir)

    bm25_index = build_bm25_plus_index(embedded)
    save_bm25_index(bm25_index, store_dir)

    return {
        "total_pdfs":        len(pdf_paths),
        "total_chunks":      len(embedded),
        "chunks_dropped":    dropped,
        "store_dir":         str(store_dir),
        "bm25_unique_terms": len(bm25_index["doc_freqs"]),
    }
