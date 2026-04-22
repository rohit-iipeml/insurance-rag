import ReactMarkdown from "react-markdown";

const VERDICT_STYLES = {
  "COVERED: Yes": {
    background: "#dcfce7",
    color: "#15803d",
    border: "1px solid #bbf7d0",
  },
  "COVERED: No": {
    background: "#fee2e2",
    color: "#b91c1c",
    border: "1px solid #fecaca",
  },
  "COVERED: Conditional": {
    background: "#fff7ed",
    color: "#c2410c",
    border: "1px solid #fed7aa",
  },
};

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

  // Extract verdict badge line if present
  let verdictKey = null;
  let bodyContent = content;
  for (const key of Object.keys(VERDICT_STYLES)) {
    if (content.startsWith(key)) {
      verdictKey = key;
      bodyContent = content.slice(key.length).replace(/^\n+/, "");
      break;
    }
  }

  const formattedContent = bodyContent
    // Strip any existing asterisks around the section headers first
    .replace(/\*{0,2}(BASE RULE|MODIFIER|NET EFFECT)\*{0,2}/g, "\n\n**$1**\n\n")
    // Clean up excessive blank lines
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  const sources = response?.sources;
  const hasSources = sources && sources.length > 0;

  return (
    <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 16 }}>
      <div
        style={{
          maxWidth: "82%",
          fontSize: 14,
          color: "var(--text-primary)",
        }}
      >
        {verdictKey && (
          <div
            style={{
              display: "inline-block",
              padding: "4px 12px",
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 600,
              border: VERDICT_STYLES[verdictKey].border,
              background: VERDICT_STYLES[verdictKey].background,
              color: VERDICT_STYLES[verdictKey].color,
              marginBottom: 12,
            }}
          >
            {verdictKey}
          </div>
        )}
        <div className="assistant-content">
          <ReactMarkdown>{formattedContent}</ReactMarkdown>
        </div>
        {hasSources && (
          <div style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                letterSpacing: "0.08em",
                color: "var(--text-secondary)",
                marginBottom: 8,
                marginTop: 16,
                textTransform: "uppercase",
              }}
            >
              Sources
            </div>
            {sources.map((src, i) => {
              const section = src.section?.length > 40
                ? src.section.slice(0, 40) + "…"
                : src.section;
              return (
                <div
                  key={i}
                  style={{
                    background: "#f7f7f5",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    padding: "8px 12px",
                    marginBottom: 6,
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 12,
                    color: "var(--text-secondary)",
                  }}
                >
                  <span>📄</span>
                  <span>
                    <span style={{ fontWeight: 500, color: "var(--text-primary)" }}>
                      {src.source}
                    </span>
                    {" · p."}{src.page}{" · "}{section}
                  </span>
                </div>
              );
            })}
            {response.citation_check?.hallucinated_citations?.length > 0 && (
              <div style={{ fontSize: 12, color: "#b45309", marginTop: 6 }}>
                ⚠ Unverified citations:{" "}
                {response.citation_check.hallucinated_citations.join(", ")}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
