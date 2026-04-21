export default function SourcesDrawer({ sources, citationCheck }) {
  const hallucinated = citationCheck?.hallucinated_citations;
  const hasWarning = hallucinated && hallucinated.length > 0;

  return (
    <details
      style={{
        border: "1px solid var(--border)",
        borderRadius: 8,
        background: "#fafaf8",
        marginTop: 10,
        maxWidth: "82%",
      }}
    >
      <summary
        style={{
          fontSize: 12,
          color: "var(--text-secondary)",
          fontWeight: 500,
          cursor: "pointer",
          padding: "8px 12px",
          listStyle: "none",
        }}
      >
        View sources ({sources.length})
      </summary>

      <div style={{ padding: "0 12px 10px" }}>
        {sources.map((src, i) => (
          <div
            key={i}
            style={{
              fontSize: 12,
              color: "var(--text-secondary)",
              padding: "3px 0",
              borderBottom: i < sources.length - 1 ? "1px solid var(--border)" : "none",
            }}
          >
            {src.source ?? "?"}  |  Page {src.page ?? "?"}  |  {src.section ?? "?"}  |  {src.doc_type ?? "?"}
          </div>
        ))}

        {hasWarning && (
          <div style={{ color: "#b45309", fontSize: 12, marginTop: 6 }}>
            ⚠ Unverified citations: {hallucinated.join(", ")}
          </div>
        )}
      </div>
    </details>
  );
}
