import { useState } from "react";
import { queryRAGStream } from "./api";
import Sidebar from "./components/Sidebar";
import ChatWindow from "./components/ChatWindow";
import WelcomeScreen from "./components/WelcomeScreen";
import UploadPanel from "./components/UploadPanel";

export default function App() {
  const [activeTab, setActiveTab] = useState("chat");
  const [messages, setMessages] = useState([]);
  const [recentQueries, setRecentQueries] = useState([]);
  const [isLoading, setIsLoading] = useState(false);

  function handleSubmit(query) {
    if (isLoading) return;
    setIsLoading(true);

    setMessages((prev) => [
      ...prev,
      { role: "user", content: query, response: null },
      { role: "assistant", content: "", response: null, streaming: true },
    ]);

    setRecentQueries((prev) => {
      const deduped = [query, ...prev.filter((q) => q !== query)];
      return deduped.slice(0, 5);
    });

    queryRAGStream(
      query,
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
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            streaming: false,
          };
          return updated;
        });
        setIsLoading(false);
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

  function handleNewChat() {
    setMessages([]);
  }

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onNewChat={handleNewChat}
        recentQueries={recentQueries}
      />
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {activeTab === "upload" ? (
          <UploadPanel />
        ) : messages.length === 0 ? (
          <WelcomeScreen onSubmit={handleSubmit} />
        ) : (
          <ChatWindow messages={messages} isLoading={isLoading} onSubmit={handleSubmit} />
        )}
      </div>
    </div>
  );
}
