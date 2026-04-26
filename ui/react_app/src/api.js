const BASE_URL = "http://localhost:8000";

export async function sessionIngest(files, sessionId) {
  const formData = new FormData();
  formData.append("session_id", sessionId);
  for (const file of files) {
    formData.append("files", file);
  }
  const res = await fetch(`${BASE_URL}/session/ingest`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const json = await res.json();
      detail = json.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export async function ingestFiles(files) {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  const res = await fetch(`${BASE_URL}/ingest`, { method: "POST", body: formData });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const json = await res.json();
      detail = json.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export async function queryRAGStream(query, chatHistory, sessionId, onToken, onDone, onSources, onError) {
  let res;
  try {
    res = await fetch(`${BASE_URL}/query/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, chat_history: chatHistory || [], session_id: sessionId || null }),
    });
  } catch (err) {
    onError(err.message);
    return;
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const json = await res.json();
      detail = json.detail || detail;
    } catch {}
    onError(detail);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let eventData = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value, { stream: true });
    const lines = chunk.split("\n");
    const tokensThisChunk = [];

    for (const line of lines) {
      if (line.startsWith("data:")) {
        // Normalize: strip "data:" prefix, preserve one leading space if present
        const lineContent = line.startsWith("data: ") ? line.slice(6) : line.slice(5);
        eventData += (eventData ? "\n" : "") + lineContent;
      } else if (line === "" && eventData !== "") {
        const content = eventData;
        eventData = "";

        if (content.trim() === "[DONE]") {
          if (tokensThisChunk.length > 0) {
            onToken(tokensThisChunk.join(""));
            tokensThisChunk.length = 0;
          }
          onDone();
          // keep reading — [SOURCES] event follows
          continue;
        }

        if (content.startsWith("[SOURCES]")) {
          if (tokensThisChunk.length > 0) {
            onToken(tokensThisChunk.join(""));
          }
          try {
            const data = JSON.parse(content.slice("[SOURCES]".length));
            onSources(data);
          } catch {
            onSources({ sources: [], citation_check: null });
          }
          return;
        }

        if (content.startsWith("[ERROR]")) {
          if (tokensThisChunk.length > 0) {
            onToken(tokensThisChunk.join(""));
          }
          onError(content.slice(7).trim());
          return;
        }

        if (content) {
          try {
            tokensThisChunk.push(JSON.parse(content));
          } catch {
            tokensThisChunk.push(content);
          }
        }
      }
    }

    if (tokensThisChunk.length > 0) {
      onToken(tokensThisChunk.join(""));
    }
  }
}

export async function queryRAG(query, chatHistory) {
  const res = await fetch(`${BASE_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, chat_history: chatHistory || [] }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const json = await res.json();
      detail = json.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}
