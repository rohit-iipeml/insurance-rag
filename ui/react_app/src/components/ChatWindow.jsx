import { useRef, useEffect, useState } from "react";
import MessageBubble from "./MessageBubble";

const dotStyle = (delay) => ({
  display: "inline-block",
  width: 6,
  height: 6,
  borderRadius: "50%",
  background: "var(--text-secondary)",
  margin: "0 2px",
  animation: "dotPulse 1.2s ease-in-out infinite",
  animationDelay: delay,
});

export default function ChatWindow({ messages, isLoading, onSubmit, pendingFiles, setPendingFiles, onSourceClick }) {
  const scrollRef = useRef(null);
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);
  const [inputValue, setInputValue] = useState("");

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey && inputValue.trim() && !isLoading) {
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
    <>
      <style>{`
        @keyframes dotPulse {
          0%, 80%, 100% { opacity: 0.2; }
          40% { opacity: 1; }
        }
      `}</style>

      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "32px 10%",
        }}
      >
        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            role={msg.role}
            content={msg.content}
            response={msg.response}
            onSourceClick={onSourceClick}
          />
        ))}

        {isLoading && messages[messages.length - 1]?.content === "" && (
          <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 16, paddingLeft: 2 }}>
            <div style={{
              background: "#f7f7f5",
              borderRadius: "12px 12px 12px 4px",
              padding: "10px 16px",
              display: "inline-flex",
              alignItems: "center",
              gap: 2,
            }}>
              <span style={dotStyle("0s")} />
              <span style={dotStyle("0.4s")} />
              <span style={dotStyle("0.8s")} />
            </div>
          </div>
        )}
      </div>

      <div
        style={{
          borderTop: "1px solid var(--border)",
          background: "#ffffff",
          padding: "16px 10%",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {pendingFiles.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
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
          disabled={!inputValue.trim() || isLoading}
          style={{
            width: 36,
            height: 36,
            minWidth: 36,
            borderRadius: "50%",
            background: "var(--accent)",
            color: "#ffffff",
            border: "none",
            cursor: !inputValue.trim() || isLoading ? "not-allowed" : "pointer",
            opacity: !inputValue.trim() || isLoading ? 0.4 : 1,
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
    </>
  );
}
