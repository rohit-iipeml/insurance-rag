import ReactMarkdown from "react-markdown";

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

  const formattedContent = content
    .replace(/^(COVERED: (?:Yes|No|Conditional))/m, "**$1**\n\n")
    .replace(/^(BASE RULE|MODIFIER|NET EFFECT)/gm, "**$1**")
    .replace(
      /(\*\*COVERED: (?:Yes|No|Conditional)\*\*\n\n)([a-z])/,
      (_, verdict, firstChar) => verdict + firstChar.toUpperCase()
    );

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
        <div className="assistant-content">
          <ReactMarkdown>{formattedContent}</ReactMarkdown>
        </div>
        {hasSources && (
          <div style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 500,
                color: "var(--text-secondary)",
                textTransform: "uppercase",
                letterSpacing: "0.6px",
                marginBottom: 6,
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
                    fontSize: 12,
                    color: "var(--text-secondary)",
                    padding: "2px 0",
                    display: "flex",
                    gap: 6,
                  }}
                >
                  <span style={{ fontWeight: 500, color: "var(--text-primary)", minWidth: 20 }}>
                    [{i + 1}]
                  </span>
                  <span>
                    {src.source} · p.{src.page} · {section}
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
