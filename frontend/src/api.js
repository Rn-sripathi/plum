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
  getClaim: (id) => request(`/claims/${id}`),
  listClaims: () => request("/claims"),
  evalCases: () => request("/eval/cases"),
  runEval: () => request("/eval/run", { method: "POST" }),
};
