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

const TEMPLATE_LABELS = {
  coverage_determination: { label: "Coverage Determination", color: "#1c3557", bg: "#e8f0fa" },
  limit_lookup:           { label: "Limit Lookup",           color: "#6d28d9", bg: "#ede9fe" },
  override_conflict:      { label: "Override / Conflict",    color: "#b45309", bg: "#fef3c7" },
  definition:             { label: "Definition",             color: "#0f766e", bg: "#ccfbf1" },
  general:                { label: "General",                color: "#6b6b6b", bg: "#f0f0ee" },
};

const DOC_TYPE_COLORS = {
  base_policy:  "#1c3557",
  endorsement:  "#b45309",
  amendment:    "#15803d",
  declarations: "#6d28d9",
  unknown:      "#d1d5db",
};

const INSUFFICIENT_MSG = "Insufficient evidence";

export default function MessageBubble({ role, content, response, onSourceClick }) {
  if (role === "user") {
    return (
      <div className="message-enter" style={{ display: "flex", justifyContent: "flex-end", marginBottom: 16 }}>
        <div
          style={{
            background: "var(--user-bubble)",
            borderRadius: "16px 16px 4px 16px",
            padding: "12px 16px",
            maxWidth: "72%",
            fontSize: 14,
            lineHeight: 1.55,
            color: "#ffffff",
            whiteSpace: "pre-wrap",
          }}
        >
          {content}
        </div>
      </div>
    );
  }

  // Insufficient evidence — amber banner
  const isInsufficient = content.startsWith(INSUFFICIENT_MSG) || content.includes("Insufficient evidence in the knowledge base");
  if (isInsufficient) {
    return (
      <div className="message-enter" style={{ display: "flex", justifyContent: "flex-start", marginBottom: 16 }}>
        <div style={{
          maxWidth: "82%",
          background: "#fffbeb",
          border: "1px solid #fcd34d",
          borderLeft: "4px solid #f59e0b",
          borderRadius: 8,
          padding: "12px 16px",
          fontSize: 14,
          color: "#92400e",
          lineHeight: 1.55,
        }}>
          <span style={{ fontWeight: 600 }}>⚠ Insufficient Evidence</span>
          <div style={{ marginTop: 4, fontSize: 13, color: "#b45309" }}>
            No chunks in the knowledge base met the similarity threshold for this query.
            Please consult the original policy documents or a licensed insurance professional.
          </div>
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
    .replace(/\*{0,2}(BASE RULE|MODIFIER|NET EFFECT)\*{0,2}/g, "\n\n**$1**\n\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  const sources       = response?.sources;
  const hasSources    = sources && sources.length > 0;
  const answerTemplate = response?.answer_template;
  const templateMeta  = TEMPLATE_LABELS[answerTemplate];

  return (
    <div className="message-enter" style={{ display: "flex", justifyContent: "flex-start", marginBottom: 16 }}>
      <div style={{ maxWidth: "82%", fontSize: 14, color: "var(--text-primary)" }}>

        {/* Template pill — only shown once sources arrive */}
        {templateMeta && answerTemplate !== "general" && (
          <div style={{
            display: "inline-block",
            padding: "2px 10px",
            borderRadius: 20,
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: "0.04em",
            background: templateMeta.bg,
            color: templateMeta.color,
            marginBottom: 8,
            textTransform: "uppercase",
          }}>
            {templateMeta.label}
          </div>
        )}

        {/* Verdict badge */}
        {verdictKey && (
          <div style={{
            display: "inline-block",
            padding: "4px 12px",
            borderRadius: 6,
            fontSize: 13,
            fontWeight: 600,
            border: VERDICT_STYLES[verdictKey].border,
            background: VERDICT_STYLES[verdictKey].background,
            color: VERDICT_STYLES[verdictKey].color,
            marginBottom: 12,
            marginLeft: templateMeta && answerTemplate !== "general" ? 8 : 0,
          }}>
            {verdictKey}
          </div>
        )}

        <div className="assistant-content">
          <ReactMarkdown>{formattedContent}</ReactMarkdown>
        </div>

        {/* Sources */}
        {hasSources && (
          <div style={{ borderTop: "1px solid var(--border)", paddingTop: 10, marginTop: 10 }}>
            <div style={{
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: "0.08em",
              color: "var(--text-secondary)",
              marginBottom: 8,
              textTransform: "uppercase",
            }}>
              Sources
            </div>
            {sources.map((src, i) => {
              const section  = src.section?.length > 40 ? src.section.slice(0, 40) + "…" : src.section;
              const docColor = DOC_TYPE_COLORS[src.doc_type] || DOC_TYPE_COLORS.unknown;
              return (
                <div
                  key={i}
                  onClick={() => onSourceClick && onSourceClick(src)}
                  style={{
                    background: "#fafaf8",
                    border: "1px solid #eeeeeb",
                    borderLeft: `3px solid ${docColor}`,
                    borderRadius: 6,
                    padding: "7px 12px",
                    marginBottom: 4,
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 12,
                    color: "var(--text-secondary)",
                    cursor: onSourceClick ? "pointer" : "default",
                    transition: "background 0.12s",
                  }}
                  onMouseEnter={(e) => { if (onSourceClick) e.currentTarget.style.background = "#f0f0ee"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "#fafaf8"; }}
                >
                  {src.citation_num ? (
                    <span style={{
                      width: 20, height: 20, borderRadius: "50%",
                      background: docColor, color: "#fff",
                      fontSize: 10, fontWeight: 700,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      flexShrink: 0,
                    }}>
                      {src.citation_num}
                    </span>
                  ) : (
                    <span style={{
                      width: 6, height: 6, borderRadius: "50%",
                      background: docColor, flexShrink: 0,
                    }} />
                  )}
                  <span>
                    <span style={{ fontWeight: 500, color: "var(--text-primary)" }}>
                      {src.source}
                    </span>
                    {" · p."}{src.page}{" · "}{section}
                  </span>
                  {src.doc_type && src.doc_type !== "unknown" && (
                    <span style={{
                      marginLeft: "auto",
                      fontSize: 10,
                      fontWeight: 600,
                      letterSpacing: "0.04em",
                      color: docColor,
                      textTransform: "uppercase",
                      flexShrink: 0,
                    }}>
                      {src.doc_type.replace("_", " ")}
                    </span>
                  )}
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
