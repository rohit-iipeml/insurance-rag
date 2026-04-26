import { useState, useEffect } from "react";
import { queryRAGStream, sessionIngest } from "./api";
import Sidebar from "./components/Sidebar";
import ChatWindow from "./components/ChatWindow";
import WelcomeScreen from "./components/WelcomeScreen";
import UploadPanel from "./components/UploadPanel";
import PDFViewer from "./components/PDFViewer";

export default function App() {
  const [sessionId] = useState(() => crypto.randomUUID());
  const [activeTab, setActiveTab] = useState("chat");
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [viewerSource, setViewerSource] = useState(null);

  // Each session: { id, title, messages }
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);

  async function handleSubmit(query, filesToIngest = []) {
    if (isLoading) return;
    setIsLoading(true);

    if (filesToIngest.length > 0) {
      try {
        await sessionIngest(filesToIngest, sessionId);
      } catch (err) {
        setIsLoading(false);
        return;
      }
    }

    // If no active session yet, create one with this query as title
    let chatSid = activeSessionId;
    if (!chatSid) {
      chatSid = Date.now().toString();
      setActiveSessionId(chatSid);
      setSessions(prev => [{
        id: chatSid,
        title: query.length > 40 ? query.slice(0, 40) + "…" : query,
        messages: []
      }, ...prev].slice(0, 10));
    }

    const chatHistory = messages
      .filter(m => m.role === "user" || (m.role === "assistant" && m.content && !m.streaming))
      .map(m => ({ role: m.role, content: m.content }))
      .slice(-6);

    setMessages((prev) => [
      ...prev,
      { role: "user", content: query, response: null },
      { role: "assistant", content: "", response: null, streaming: true },
    ]);

    queryRAGStream(
      query,
      chatHistory,
      sessionId,
      (token) => {
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: updated[updated.length - 1].content + token,
          };
          return updated;
        });
      },
      () => {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant") {
            updated[updated.length - 1] = {
              ...last,
              streaming: false,
              content: (() => {
                  let t = last.content;
                  // Pattern 1: **BASE RULE** (with or without asterisks)
                  t = t.replace(/\*{0,2}BASE RULE\*{0,2}/g, "\n\n**BASE RULE**\n\n");
                  // Pattern 2: MODIFIER** or **MODIFIER** or ODIFIER** (M sometimes dropped)
                  t = t.replace(/\*{0,2}M?ODIFIER\*{0,2}/g, "\n\n**MODIFIER**\n\n");
                  // Pattern 3: EFFECT** or NET EFFECT** (NET sometimes dropped)
                  t = t.replace(/\*{0,2}(NET )?EFFECT\*{0,2}/g, "\n\n**NET EFFECT**\n\n");
                  // Cleanup
                  t = t.replace(/\n{3,}/g, "\n\n").trim();
                  return t;
                })(),
            };
          }
          return updated;
        });
        setIsLoading(false);
      },
      (data) => {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          updated[updated.length - 1] = {
            ...last,
            response: data,
          };
          return updated;
        });
      },
      (errMsg) => {
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: "⚠️ " + errMsg,
            streaming: false,
          };
          return updated;
        });
        setIsLoading(false);
      }
    );
  }

  function handleSourceClick(src) {
    setViewerSource({
      filename:  src.source,
      sessionId: sessionId,
      page:      src.page,
      section:   src.section,
      chunkText: src.chunk_text || "",
      isSession: src.is_session || false,
    });
  }

  function handleNewChat() {
    setMessages([]);
    setActiveSessionId(null);
  }

  useEffect(() => {
    if (!activeSessionId || messages.length === 0) return;
    setSessions(prev => prev.map(s =>
      s.id === activeSessionId ? { ...s, messages } : s
    ));
  }, [messages, activeSessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleSessionClick(session) {
    if (session.id === activeSessionId) return;
    setMessages(session.messages || []);
    setActiveSessionId(session.id);
    setActiveTab("chat");
  }

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onNewChat={handleNewChat}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSessionClick={handleSessionClick}
      />
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {activeTab === "upload" ? (
          <UploadPanel />
        ) : messages.length === 0 ? (
          <WelcomeScreen
            onSubmit={handleSubmit}
            pendingFiles={pendingFiles}
            setPendingFiles={setPendingFiles}
          />
        ) : (
          <ChatWindow
            messages={messages}
            isLoading={isLoading}
            onSubmit={handleSubmit}
            pendingFiles={pendingFiles}
            setPendingFiles={setPendingFiles}
            onSourceClick={handleSourceClick}
          />
        )}
      </div>
      {viewerSource && (
        <>
          <div
            onClick={() => setViewerSource(null)}
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(0,0,0,0.25)",
              zIndex: 999,
            }}
          />
          <PDFViewer
            source={viewerSource}
            onClose={() => setViewerSource(null)}
          />
        </>
      )}
    </div>
  );
}
