import { useState, useRef } from "react";

const PROMPTS = [
  "Is water damage from frozen pipes covered if vacant 65 days?",
  "Does endorsement NX-END-02 override Section 7.3?",
  "What is the hurricane deductible for Florida properties?",
  "What endorsements are attached to the John Smith policy?",
];

export default function WelcomeScreen({ onSubmit, pendingFiles, setPendingFiles }) {
  const [inputValue, setInputValue] = useState("");
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey && inputValue.trim()) {
      e.preventDefault();
      submit();
    }
  }

  function handleChange(e) {
    setInputValue(e.target.value);
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
  }

  function submit() {
    const val = inputValue.trim();
    if (!val) return;
    const filesToSend = [...pendingFiles];
    setPendingFiles([]);
    onSubmit(val, filesToSend);
    setInputValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }

  return (
    <div style={{ position: "relative", height: "100%" }}>
      {/* Centered content — bottom padding reserves space for the input bar */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
          padding: "40px 40px 120px 40px",
        }}
      >
        <div style={{
          width: 48, height: 48, borderRadius: 12, background: "var(--accent)",
          display: "flex", alignItems: "center", justifyContent: "center",
          marginBottom: 16, fontSize: 22,
        }}>
          📋
        </div>

        <h1
          style={{
            fontSize: 26,
            fontWeight: 600,
            color: "var(--text-primary)",
            letterSpacing: "-0.5px",
            marginBottom: 8,
            textAlign: "center",
          }}
        >
          What would you like to know?
        </h1>

        <p
          style={{
            fontSize: 15,
            color: "var(--text-secondary)",
            marginBottom: 36,
            textAlign: "center",
          }}
        >
          Ask about coverage, exclusions, deductibles, or policy terms.
        </p>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 10,
            width: "100%",
            maxWidth: 640,
          }}
        >
          {PROMPTS.map((prompt) => (
            <button
              key={prompt}
              onClick={() => onSubmit(prompt)}
              style={{
                background: "#ffffff",
                border: "1px solid var(--border)",
                borderLeft: "3px solid transparent",
                borderRadius: 10,
                padding: 14,
                fontSize: 13,
                fontWeight: 400,
                textAlign: "left",
                lineHeight: 1.4,
                cursor: "pointer",
                width: "100%",
                color: "var(--text-primary)",
                transition: "all 0.15s",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "#f5f5f3";
                e.currentTarget.style.borderLeftColor = "var(--accent)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "#ffffff";
                e.currentTarget.style.borderLeftColor = "#e8e8e4";
              }}
            >
              {prompt}
            </button>
          ))}
        </div>
      </div>

      {/* Input bar pinned to bottom */}
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
          borderTop: "1px solid var(--border)",
          background: "#fafaf9",
          padding: "16px 10%",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {pendingFiles.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {pendingFiles.map((f) => (
              <div
                key={f.name}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  background: "#f0f0ee",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  padding: "3px 8px",
                  fontSize: 12,
                  color: "var(--text-primary)",
                }}
              >
                <span>📄</span>
                <span>{f.name}</span>
                <button
                  onClick={() => setPendingFiles((prev) => prev.filter((x) => x.name !== f.name))}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: "var(--text-secondary)",
                    fontSize: 13,
                    padding: "0 2px",
                    lineHeight: 1,
                  }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <button
            onClick={() => fileInputRef.current?.click()}
            title="Attach PDF"
            style={{
              width: 36,
              height: 36,
              minWidth: 36,
              borderRadius: "50%",
              background: "transparent",
              border: "1px solid var(--border)",
              cursor: "pointer",
              fontSize: 16,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--text-secondary)",
            }}
          >
            📎
          </button>
          <textarea
            ref={textareaRef}
            rows={1}
            value={inputValue}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder="Ask about a policy, coverage, or exclusion…"
            style={{
              flex: 1,
              resize: "none",
              border: "1px solid var(--border)",
              borderRadius: 10,
              padding: "10px 14px",
              fontSize: 14,
              fontFamily: "inherit",
              outline: "none",
              background: "#ffffff",
              color: "var(--text-primary)",
              overflowY: "hidden",
              lineHeight: 1.5,
            }}
            onFocus={(e) => (e.target.style.borderColor = "#aaaaaa")}
            onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
          />
          <button
            onClick={submit}
            disabled={!inputValue.trim()}
            style={{
              width: 36,
              height: 36,
              minWidth: 36,
              borderRadius: "50%",
              background: "var(--accent)",
              color: "#ffffff",
              border: "none",
              cursor: !inputValue.trim() ? "not-allowed" : "pointer",
              opacity: !inputValue.trim() ? 0.4 : 1,
              fontSize: 16,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            ↑
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            multiple
            style={{ display: "none" }}
            onChange={(e) => {
              const incoming = Array.from(e.target.files || []);
              setPendingFiles((prev) => {
                const names = new Set(prev.map((f) => f.name));
                return [...prev, ...incoming.filter((f) => !names.has(f.name))];
              });
              e.target.value = "";
            }}
          />
        </div>
      </div>
    </div>
  );
}
