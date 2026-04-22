const BASE_URL = "http://localhost:8000";

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

export async function queryRAGStream(query, chatHistory, onToken, onDone, onSources, onError) {
  let res;
  try {
    res = await fetch(`${BASE_URL}/query/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, chat_history: chatHistory || [] }),
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
  let buffer = "";
  let awaitingSources = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Split on double-newline (SSE event boundary)
    const events = buffer.split("\n\n");
    buffer = events.pop(); // keep any incomplete trailing event

    for (const event of events) {
      if (!event.trim()) continue;
      // Each event line is "data: <content>" — slice(6) removes exactly
      // "data: " (6 chars) and preserves everything after, including any
      // leading space that is part of the token itself.
      const content = event
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.startsWith("data: ") ? line.slice(6) : line.slice(5))
        .join("\n");

      if (awaitingSources) {
        try {
          const parsed = JSON.parse(content.slice("[SOURCES]".length));
          onSources(parsed);
        } catch {
          onSources({ sources: [], citation_check: null });
        }
        return;
      } else if (content.trim() === "[DONE]") {
        onDone();
        awaitingSources = true;
      } else if (content.startsWith("[ERROR]")) {
        onError(content.slice(7));
        return;
      } else if (content.trim()) {
        onToken(content);
      }
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
