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

export async function queryRAGStream(query, onToken, onDone, onError) {
  let res;
  try {
    res = await fetch(`${BASE_URL}/query/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
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

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Split on double-newline (SSE event boundary)
    const events = buffer.split("\n\n");
    buffer = events.pop(); // keep any incomplete trailing event

    for (const event of events) {
      if (!event.trim()) continue;
      // Each event line is "data: <content>"; collect all data lines for multi-line events
      const content = event
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");

      if (content === "[DONE]") {
        onDone();
        return;
      } else if (content.startsWith("[ERROR]")) {
        onError(content.slice(7).trim());
        return;
      } else {
        onToken(content);
      }
    }
  }
}

export async function queryRAG(query) {
  const res = await fetch(`${BASE_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
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
