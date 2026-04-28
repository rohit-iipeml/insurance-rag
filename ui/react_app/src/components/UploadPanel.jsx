import { useState, useRef, useEffect } from "react";
import { ingestFiles, getStats } from "../api";

export default function UploadPanel() {
  const [files, setFiles] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);
  const fileInputRef = useRef(null);
  const dropZoneRef = useRef(null);

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
  }, []);

  function addFiles(incoming) {
    const pdfs = Array.from(incoming).filter((f) =>
      f.name.toLowerCase().endsWith(".pdf")
    );
    setFiles((prev) => {
      const names = new Set(prev.map((f) => f.name));
      return [...prev, ...pdfs.filter((f) => !names.has(f.name))];
    });
  }

  function removeFile(name) {
    setFiles((prev) => prev.filter((f) => f.name !== name));
  }

  function handleDragOver(e) {
    e.preventDefault();
    if (dropZoneRef.current) dropZoneRef.current.style.borderColor = "var(--accent)";
  }

  function handleDragLeave() {
    if (dropZoneRef.current) dropZoneRef.current.style.borderColor = "var(--border)";
  }

  function handleDrop(e) {
    e.preventDefault();
    if (dropZoneRef.current) dropZoneRef.current.style.borderColor = "var(--border)";
    addFiles(e.dataTransfer.files);
  }

  async function handleIngest() {
    if (!files.length || isLoading) return;
    setIsLoading(true);
    setResult(null);
    setError(null);
    try {
      const data = await ingestFiles(files);
      setResult(data);
      getStats().then(setStats).catch(() => {});
      setFiles([]);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "100%",
        padding: 40,
      }}
    >
      <div style={{ maxWidth: 560, width: "100%" }}>
        {stats && stats.loaded && (
          <div style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 10,
            padding: "20px 24px",
            marginBottom: 28,
          }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text-secondary)", marginBottom: 14, letterSpacing: "0.05em", textTransform: "uppercase" }}>
              Knowledge Base
            </div>

            {/* Top-level numbers */}
            <div style={{ display: "flex", gap: 32, marginBottom: 20 }}>
              {[
                { label: "PDFs", value: stats.total_pdfs },
                { label: "Chunks", value: stats.total_chunks.toLocaleString() },
                { label: "Index Terms", value: stats.bm25_terms.toLocaleString() },
              ].map(({ label, value }) => (
                <div key={label}>
                  <div style={{ fontSize: 26, fontWeight: 700, color: "var(--text-primary)", lineHeight: 1 }}>
                    {value}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
                    {label}
                  </div>
                </div>
              ))}
            </div>

            {/* State Coverage */}
            {stats.jurisdiction_counts && Object.keys(stats.jurisdiction_counts).length > 0 && (
              <div>
                <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 8, fontWeight: 500 }}>
                  State Coverage
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {Object.entries(stats.jurisdiction_counts)
                    .sort((a, b) => b[1] - a[1])
                    .map(([state, count]) => {
                      const max = Math.max(...Object.values(stats.jurisdiction_counts));
                      const pct = Math.round((count / max) * 100);
                      return (
                        <div key={state} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <div style={{ width: 28, fontSize: 12, fontWeight: 600, color: "var(--text-primary)", flexShrink: 0 }}>
                            {state}
                          </div>
                          <div style={{ flex: 1, background: "var(--border)", borderRadius: 3, height: 6, overflow: "hidden" }}>
                            <div style={{ width: `${pct}%`, background: "var(--accent)", height: "100%", borderRadius: 3 }} />
                          </div>
                          <div style={{ fontSize: 12, color: "var(--text-secondary)", width: 60, textAlign: "right" }}>
                            {count} chunks
                          </div>
                        </div>
                      );
                    })}
                </div>
              </div>
            )}
          </div>
        )}

        <h2 style={{ fontSize: 22, fontWeight: 600, marginBottom: 8, color: "var(--text-primary)" }}>
          Upload Policy Documents
        </h2>
        <p style={{ fontSize: 14, color: "var(--text-secondary)", marginBottom: 24 }}>
          Upload one or more PDF files to add them to the knowledge base.
        </p>

        {/* Drop zone */}
        <div
          ref={dropZoneRef}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          style={{
            border: "2px dashed var(--border)",
            borderRadius: 8,
            height: 160,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            flexDirection: "column",
            gap: 8,
            color: "var(--text-secondary)",
            fontSize: 14,
            transition: "border-color 0.15s",
          }}
        >
          <span style={{ fontSize: 28 }}>📄</span>
          Drag PDFs here or click to browse
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          multiple
          style={{ display: "none" }}
          onChange={(e) => addFiles(e.target.files)}
        />

        {/* File list */}
        {files.length > 0 && (
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 4 }}>
            {files.map((f) => (
              <div
                key={f.name}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  fontSize: 13,
                  color: "var(--text-primary)",
                }}
              >
                <span>{f.name}</span>
                <button
                  onClick={() => removeFile(f.name)}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: "var(--text-secondary)",
                    fontSize: 14,
                    padding: "0 4px",
                  }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Ingest button */}
        <button
          onClick={handleIngest}
          disabled={files.length === 0 || isLoading}
          style={{
            width: "100%",
            background: "var(--accent)",
            color: "#ffffff",
            border: "none",
            borderRadius: 8,
            padding: 12,
            fontSize: 14,
            fontWeight: 500,
            cursor: files.length === 0 || isLoading ? "not-allowed" : "pointer",
            opacity: files.length === 0 || isLoading ? 0.5 : 1,
            marginTop: 16,
          }}
        >
          {isLoading ? "Ingesting…" : "Ingest Documents"}
        </button>

        {/* Success */}
        {result && (
          <div
            style={{
              background: "#f0fdf4",
              border: "1px solid #86efac",
              borderRadius: 8,
              padding: 16,
              marginTop: 16,
              fontSize: 14,
              color: "#166534",
            }}
          >
            ✓ Added {result.chunks_added} chunks from {result.total_pdfs} PDF(s).
            Knowledge base now contains {result.total_chunks} total chunks.
            {result.replaced_sources && result.replaced_sources.length > 0 && (
              <div style={{ marginTop: 6, fontSize: 13 }}>
                Updated: {result.replaced_sources.join(", ")}
              </div>
            )}
            {result.skipped_sources && result.skipped_sources.length > 0 && (
              <div style={{ marginTop: 6, fontSize: 13 }}>
                Skipped (unchanged): {result.skipped_sources.join(", ")}
              </div>
            )}
          </div>
        )}

        {/* Error */}
        {error && (
          <div
            style={{
              background: "#fef2f2",
              border: "1px solid #fca5a5",
              borderRadius: 8,
              padding: 16,
              marginTop: 16,
              fontSize: 14,
              color: "#991b1b",
            }}
          >
            ✗ {error}
          </div>
        )}
      </div>
    </div>
  );
}
