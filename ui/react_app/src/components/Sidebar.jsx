export default function Sidebar({ activeTab, setActiveTab, onNewChat, sessions, activeSessionId, onSessionClick }) {
  const navItems = [
    { id: "chat", label: "💬 Chat" },
    { id: "upload", label: "📂 Upload Docs" },
  ];

  return (
    <div
      style={{
        width: 240,
        minWidth: 240,
        height: "100%",
        background: "var(--sidebar-bg)",
        borderRight: "1px solid var(--border)",
        display: "flex",
        flexDirection: "column",
        padding: "20px 16px",
        boxSizing: "border-box",
        overflow: "hidden",
      }}
    >
      {/* Brand */}
      <div
        style={{
          fontSize: 18,
          fontWeight: 600,
          color: "var(--text-primary)",
          marginBottom: 20,
        }}
      >
        📋 Clairo
      </div>

      {/* Divider */}
      <div
        style={{
          borderTop: "1px solid var(--border)",
          marginBottom: 16,
        }}
      />

      {/* New Chat button */}
      <button
        onClick={() => { onNewChat(); setActiveTab("chat"); }}
        style={{
          width: "100%",
          background: "var(--accent)",
          color: "#ffffff",
          border: "none",
          borderRadius: 8,
          padding: "10px 16px",
          fontSize: 13,
          fontWeight: 500,
          cursor: "pointer",
          marginBottom: 16,
          textAlign: "center",
        }}
      >
        + New Chat
      </button>

      {/* Tab switcher */}
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {navItems.map((item) => {
          const isActive = activeTab === item.id;
          return (
            <div
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              style={{
                padding: "8px 10px",
                borderRadius: 6,
                fontSize: 13,
                cursor: "pointer",
                fontWeight: isActive ? 500 : 400,
                color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
                background: isActive ? "#ebebea" : "transparent",
                userSelect: "none",
              }}
            >
              {item.label}
            </div>
          );
        })}
      </div>

      {/* Recent sessions */}
      {sessions.length > 0 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 500, color: "var(--text-secondary)",
                        letterSpacing: "0.6px", textTransform: "uppercase",
                        margin: "16px 0 8px" }}>
            Recent
          </div>
          {sessions.map(session => (
            <div
              key={session.id}
              onClick={() => onSessionClick(session)}
              style={{
                fontSize: 13,
                color: session.id === activeSessionId ? "var(--text-primary)" : "var(--text-secondary)",
                padding: "6px 10px",
                borderRadius: 6,
                cursor: "pointer",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                background: session.id === activeSessionId ? "#eeeeeb" : "transparent",
              }}
            >
              {session.title}
            </div>
          ))}
        </>
      )}

      {/* Footer */}
      <div
        style={{
          marginTop: "auto",
          paddingTop: 16,
          fontSize: 11,
          color: "#aaaaaa",
          textAlign: "center",
        }}
      >
        Insurance Policy Assistant
      </div>
    </div>
  );
}
