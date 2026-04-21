import SourcesDrawer from "./SourcesDrawer";

export default function MessageBubble({ role, content, response }) {
  if (role === "user") {
    return (
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 16 }}>
        <div
          style={{
            background: "var(--user-bubble)",
            borderRadius: "16px 16px 4px 16px",
            padding: "12px 16px",
            maxWidth: "72%",
            fontSize: 14,
            lineHeight: 1.55,
            color: "var(--text-primary)",
            whiteSpace: "pre-wrap",
          }}
        >
          {content}
        </div>
      </div>
    );
  }

  const sources = response?.sources;
  const hasSources = sources && sources.length > 0;

  return (
    <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 16 }}>
      <div
        style={{
          maxWidth: "82%",
          fontSize: 14,
          lineHeight: 1.65,
          color: "var(--text-primary)",
          whiteSpace: "pre-wrap",
        }}
      >
        {content}
        {hasSources && (
          <SourcesDrawer sources={sources} citationCheck={response.citation_check} />
        )}
      </div>
    </div>
  );
}
