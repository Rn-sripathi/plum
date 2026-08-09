const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const message = body.message || body.detail || `HTTP ${resp.status}`;
    throw Object.assign(new Error(message), { status: resp.status, body });
  }
  return body;
}

async function upload(path, formData) {
  // No Content-Type header — the browser sets the multipart boundary.
  const resp = await fetch(`${BASE}${path}`, { method: "POST", body: formData });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const message = body.message || body.detail || `HTTP ${resp.status}`;
    throw Object.assign(new Error(message), { status: resp.status, body });
  }
  return body;
}

/**
 * Read a Server-Sent Events response, invoking `onEvent(name, data)` per event.
 * EventSource cannot POST, so the stream is parsed off fetch's body reader.
 */
async function readSSE(resp, onEvent) {
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    const message = body.message || body.detail || `HTTP ${resp.status}`;
    throw Object.assign(new Error(message), { status: resp.status, body });
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop();
    for (const frame of frames) {
      let name = "message";
      let payload = null;
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) name = line.slice(7).trim();
        else if (line.startsWith("data: ")) payload = line.slice(6);
      }
      if (payload !== null) onEvent(name, JSON.parse(payload));
    }
  }
}

/** Drive an SSE response to its terminal event, returning the result. */
async function consume(resp, onStep) {
  let result = null;
  let failure = null;
  await readSSE(resp, (name, data) => {
    if (name === "step") onStep?.(data);
    else if (name === "result") result = data;
    else if (name === "error") failure = data;
  });
  if (failure) {
    throw Object.assign(new Error(failure.message || "Processing failed"), {
      status: 503,
      body: failure,
    });
  }
  if (!result) throw new Error("Stream ended before a decision was produced.");
  return result;
}

export const api = {
  health: () => request("/health"),
  submitClaim: (submission) =>
    request("/claims", { method: "POST", body: JSON.stringify(submission) }),
  uploadClaim: (metadata, files, documentTypes) => {
    const form = new FormData();
    form.append("metadata", JSON.stringify(metadata));
    form.append("document_types", documentTypes.join(","));
    files.forEach((file) => form.append("files", file));
    return upload("/claims/upload", form);
  },

  /** Streams trace steps as the decision is made. Resolves with the result. */
  submitClaimStreaming: async (submission, onStep) => {
    const resp = await fetch(`${BASE}/claims/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(submission),
    });
    return consume(resp, onStep);
  },

  uploadClaimStreaming: async (metadata, files, documentTypes, onStep) => {
    const form = new FormData();
    form.append("metadata", JSON.stringify(metadata));
    form.append("document_types", documentTypes.join(","));
    files.forEach((file) => form.append("files", file));
    const resp = await fetch(`${BASE}/claims/upload/stream`, { method: "POST", body: form });
    return consume(resp, onStep);
  },
  getClaim: (id) => request(`/claims/${id}`),
  listClaims: () => request("/claims"),
  evalCases: () => request("/eval/cases"),
  runEval: () => request("/eval/run", { method: "POST" }),
};
