import { useEffect, useState } from "react";
import { api } from "../api";

const CATEGORIES = [
  "CONSULTATION", "DIAGNOSTIC", "PHARMACY", "DENTAL", "VISION", "ALTERNATIVE_MEDICINE",
];

const DOC_TYPES = [
  "PRESCRIPTION", "HOSPITAL_BILL", "PHARMACY_BILL", "LAB_REPORT",
  "DIAGNOSTIC_REPORT", "DISCHARGE_SUMMARY", "DENTAL_REPORT",
];

const BLANK = {
  member_id: "EMP001",
  policy_id: "PLUM_GHI_2024",
  claim_category: "CONSULTATION",
  treatment_date: "2024-11-01",
  claimed_amount: 1500,
  hospital_name: "",
};

export default function SubmitForm({ onResult, onStep, onStart }) {
  const [mode, setMode] = useState("upload"); // "upload" | "structured"
  const [cases, setCases] = useState([]);
  const [preset, setPreset] = useState("");
  const [form, setForm] = useState(BLANK);
  const [docsJson, setDocsJson] = useState("[]");
  const [files, setFiles] = useState([]);
  const [fileTypes, setFileTypes] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.evalCases().then((data) => setCases(data.test_cases)).catch(() => setCases([]));
  }, []);

  function loadPreset(caseId) {
    setPreset(caseId);
    const found = cases.find((c) => c.case_id === caseId);
    if (!found) return;
    const { documents, ...rest } = found.input;
    setForm({ ...BLANK, ...rest });
    setDocsJson(JSON.stringify(documents, null, 2));
    setError(null);
  }

  function set(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function pickFiles(fileList) {
    const picked = Array.from(fileList);
    setFiles(picked);
    setFileTypes(picked.map(() => ""));
    setError(null);
  }

  function setFileType(index, value) {
    setFileTypes((types) => types.map((t, i) => (i === index ? value : t)));
  }

  async function submit(e) {
    e.preventDefault();
    setError(null);

    const metadata = { ...form, claimed_amount: Number(form.claimed_amount) };
    if (!metadata.hospital_name) delete metadata.hospital_name;

    let documents;
    if (mode === "upload") {
      if (!files.length) {
        setError("Select at least one document to upload.");
        return;
      }
    } else {
      try {
        documents = JSON.parse(docsJson);
      } catch {
        setError("Documents JSON is invalid.");
        return;
      }
    }

    setBusy(true);
    onStart?.();
    try {
      const result =
        mode === "upload"
          ? await api.uploadClaimStreaming(metadata, files, fileTypes, onStep)
          : await api.submitClaimStreaming({ ...metadata, documents }, onStep);
      onResult(result);
    } catch (err) {
      setError(`${err.status || ""} ${err.message}`.trim());
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>Submit a claim</h2>

      <div className="tabs">
        <button
          type="button"
          className={mode === "upload" ? "tab active" : "tab"}
          onClick={() => setMode("upload")}
        >
          Upload documents
        </button>
        <button
          type="button"
          className={mode === "structured" ? "tab active" : "tab"}
          onClick={() => setMode("structured")}
        >
          Structured (eval cases)
        </button>
      </div>

      <div className="row">
        <div>
          <label>Member ID</label>
          <input value={form.member_id} onChange={(e) => set("member_id", e.target.value)} />
        </div>
        <div>
          <label>Treatment type</label>
          <select value={form.claim_category} onChange={(e) => set("claim_category", e.target.value)}>
            {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
          </select>
        </div>
      </div>

      <div className="row">
        <div>
          <label>Treatment date</label>
          <input type="date" value={form.treatment_date} onChange={(e) => set("treatment_date", e.target.value)} />
        </div>
        <div>
          <label>Claimed amount (₹)</label>
          <input type="number" min="1" value={form.claimed_amount} onChange={(e) => set("claimed_amount", e.target.value)} />
        </div>
      </div>

      <label>Hospital name (optional — enables network discount)</label>
      <input
        value={form.hospital_name || ""}
        onChange={(e) => set("hospital_name", e.target.value)}
        placeholder="e.g. Apollo Hospitals"
      />

      {mode === "upload" ? (
        <>
          <label>Documents (images or PDFs)</label>
          <input
            type="file"
            multiple
            accept="image/*,application/pdf"
            onChange={(e) => pickFiles(e.target.files)}
          />
          {files.length > 0 && (
            <table>
              <thead>
                <tr><th>File</th><th>Declared type</th></tr>
              </thead>
              <tbody>
                {files.map((file, i) => (
                  <tr key={file.name + i}>
                    <td>{file.name}</td>
                    <td>
                      <select value={fileTypes[i]} onChange={(e) => setFileType(i, e.target.value)}>
                        <option value="">Auto-detect (vision)</option>
                        {DOC_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="hint">
            Leave the type as <b>Auto-detect</b> to let GPT-4o vision classify each document and
            extract its fields. Declare a type instead to have the system cross-check what you
            claimed against what the document actually is. Sample documents:{" "}
            <code>data/mock_documents/</code>.
          </div>
        </>
      ) : (
        <>
          <label>Load a test-case preset</label>
          <select value={preset} onChange={(e) => loadPreset(e.target.value)}>
            <option value="">— choose a case —</option>
            {cases.map((c) => (
              <option key={c.case_id} value={c.case_id}>
                {c.case_id} — {c.case_name}
              </option>
            ))}
          </select>

          <label>Documents (pre-extracted JSON)</label>
          <textarea value={docsJson} onChange={(e) => setDocsJson(e.target.value)} spellCheck={false} />
          <div className="hint">
            The assignment's 12 evaluation cases supply document contents as structured data
            rather than image files. This mode replays them through the identical pipeline —
            only the extraction stage differs, and the trace records that it was skipped.
          </div>
        </>
      )}

      {error && <div className="error-box section-gap">{error}</div>}

      <div className="actions">
        <button type="submit" disabled={busy}>{busy ? "Processing…" : "Submit claim"}</button>
        {mode === "structured" && (
          <button type="button" className="secondary" onClick={() => loadPreset(preset)} disabled={!preset}>
            Reset preset
          </button>
        )}
      </div>
    </form>
  );
}
