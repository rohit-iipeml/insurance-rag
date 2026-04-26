import { Viewer, Worker } from "@react-pdf-viewer/core";
import { defaultLayoutPlugin } from "@react-pdf-viewer/default-layout";
import { searchPlugin } from "@react-pdf-viewer/search";
import "@react-pdf-viewer/core/lib/styles/index.css";
import "@react-pdf-viewer/default-layout/lib/styles/index.css";

const BASE_URL = "http://localhost:8000";

export default function PDFViewer({ source, onClose }) {
  const searchPluginInstance = searchPlugin();
  const { highlight } = searchPluginInstance;
  const defaultLayoutPluginInstance = defaultLayoutPlugin();

  const pdfUrl = source.isSession
    ? `${BASE_URL}/pdf/${source.sessionId}/${encodeURIComponent(source.filename)}`
    : `${BASE_URL}/pdf/global/${encodeURIComponent(source.filename)}`;

  function handleDocumentLoad() {
    if (source.chunkText) {
      setTimeout(() => {
        highlight([{ keyword: source.chunkText.substring(0, 80), matchCase: false }]);
      }, 300);
    }
  }

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        right: 0,
        width: "45%",
        height: "100vh",
        background: "#ffffff",
        boxShadow: "-4px 0 24px rgba(0,0,0,0.18)",
        zIndex: 1000,
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "12px 16px",
          borderBottom: "1px solid #e8e8e4",
          background: "#fafaf9",
          flexShrink: 0,
        }}
      >
        <div>
          <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>
            {source.filename}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 2 }}>
            Page {source.page} · {source.section?.length > 50 ? source.section.slice(0, 50) + "…" : source.section}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: 20,
            color: "var(--text-secondary)",
            padding: "4px 8px",
            lineHeight: 1,
          }}
        >
          ×
        </button>
      </div>

      {/* Viewer */}
      <div style={{ flex: 1, overflow: "hidden" }}>
        <Worker workerUrl="https://unpkg.com/pdfjs-dist@3.4.120/build/pdf.worker.min.js">
          <Viewer
            fileUrl={pdfUrl}
            initialPage={Math.max(0, (source.page || 1) - 1)}
            plugins={[defaultLayoutPluginInstance, searchPluginInstance]}
            onDocumentLoad={handleDocumentLoad}
          />
        </Worker>
      </div>
    </div>
  );
}
