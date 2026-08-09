import { useEffect, useState } from "react";
import { api } from "../api";

const CATEGORIES = [
  "CONSULTATION", "DIAGNOSTIC", "PHARMACY", "DENTAL", "VISION", "ALTERNATIVE_MEDICINE",
];

const BLANK = {
  member_id: "EMP001",
  policy_id: "PLUM_GHI_2024",
  claim_category: "CONSULTATION",
  treatment_date: "2024-11-01",
  claimed_amount: 1500,
  hospital_name: "",
  documents: [],
};

export default function SubmitForm({ onResult, onBusy }) {
  const [cases, setCases] = useState([]);
  const [preset, setPreset] = useState("");
  const [form, setForm] = useState(BLANK);
  const [docsJson, setDocsJson] = useState("[]");
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

  async function submit(e) {
    e.preventDefault();
    setError(null);
    let documents;
    try {
      documents = JSON.parse(docsJson);
    } catch {
      setError("Documents JSON is invalid.");
      return;
    }
    const payload = { ...form, documents };
    if (!payload.hospital_name) delete payload.hospital_name;
    payload.claimed_amount = Number(payload.claimed_amount);
    setBusy(true);
    onBusy?.(true);
    try {
      const result = await api.submitClaim(payload);
      onResult(result);
    } catch (err) {
      setError(`${err.status || ""} ${err.message}`.trim());
    } finally {
      setBusy(false);
      onBusy?.(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>Submit a claim</h2>

      <label>Load a test-case preset</label>
      <select value={preset} onChange={(e) => loadPreset(e.target.value)}>
        <option value="">— start from scratch —</option>
        {cases.map((c) => (
          <option key={c.case_id} value={c.case_id}>
            {c.case_id} — {c.case_name}
          </option>
        ))}
      </select>

      <div className="row">
        <div>
          <label>Member ID</label>
          <input value={form.member_id} onChange={(e) => set("member_id", e.target.value)} />
        </div>
        <div>
          <label>Category</label>
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

      <label>Hospital name (optional — network discount)</label>
      <input value={form.hospital_name || ""} onChange={(e) => set("hospital_name", e.target.value)} placeholder="e.g. Apollo Hospitals" />

      <label>Documents (JSON)</label>
      <textarea value={docsJson} onChange={(e) => setDocsJson(e.target.value)} spellCheck={false} />
      <div className="hint">
        Each document: <code>file_id</code>, <code>actual_type</code>, optional <code>quality</code>,{" "}
        <code>patient_name_on_doc</code>, <code>content</code> (pre-extracted fields).
      </div>

      {error && <div className="error-box section-gap">{error}</div>}

      <div className="actions">
        <button type="submit" disabled={busy}>{busy ? "Processing…" : "Submit claim"}</button>
        <button type="button" className="secondary" onClick={() => loadPreset(preset)} disabled={!preset}>
          Reset preset
        </button>
      </div>
    </form>
  );
}
