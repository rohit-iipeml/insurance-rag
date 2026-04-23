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

export default function ChatWindow({ messages, isLoading, onSubmit }) {
  const scrollRef = useRef(null);
  const textareaRef = useRef(null);
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
    onSubmit(val);
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
          gap: 8,
          alignItems: "flex-end",
        }}
      >
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
      </div>
    </>
  );
}
