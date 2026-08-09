import TraceTimeline from "./TraceTimeline";

const inr = (v) => `₹${Number(v).toLocaleString("en-IN")}`;

function DocumentProblems({ result }) {
  return (
    <>
      <div className="section-gap">
        <span className="badge DOCUMENTS_REQUIRED">STOPPED — DOCUMENTS REQUIRED</span>
      </div>
      <p className="hint">
        No decision was made. The claim was returned to the member with specific instructions:
      </p>
      {result.problems.map((p, i) => (
        <div className="problem" key={i}>
          <div className="kind">{p.kind}{p.file_name ? ` · ${p.file_name}` : ""}</div>
          <div>{p.message}</div>
          <div className="action">→ {p.action_needed}</div>
        </div>
      ))}
    </>
  );
}

function Decision({ result }) {
  const confidence = Math.round(result.confidence * 100);
  return (
    <>
      <div className="section-gap">
        <span className={`badge ${result.decision}`}>{result.decision.replace("_", " ")}</span>
        {result.manual_review_recommended && (
          <span className="badge MANUAL_REVIEW" style={{ marginLeft: 8 }}>review recommended</span>
        )}
        {result.degraded_components?.length > 0 && (
          <span className="badge DOCUMENTS_REQUIRED" style={{ marginLeft: 8 }}>
            degraded: {result.degraded_components.join(", ")}
          </span>
        )}
      </div>

      <div className="amount">{inr(result.approved_amount)}</div>
      <div className="confidence">approved · confidence {confidence}%</div>
      <div className="meter"><div style={{ width: `${confidence}%` }} /></div>

      <h2>Why</h2>
      <ul className="reasons">
        {result.reasons.map((r, i) => <li key={i}>{r}</li>)}
      </ul>

      {result.fraud_signals?.length > 0 && (
        <div className="section-gap">
          <h2>Fraud signals</h2>
          {result.fraud_signals.map((s, i) => (
            <div className="signal" key={i}><b>{s.code}</b> — {s.detail}</div>
          ))}
        </div>
      )}

      {result.line_items?.length > 0 && (
        <div className="section-gap">
          <h2>Line items</h2>
          <table>
            <thead>
              <tr><th>Item</th><th>Claimed</th><th>Verdict</th><th>Reason</th></tr>
            </thead>
            <tbody>
              {result.line_items.map((li, i) => (
                <tr key={i}>
                  <td>{li.description}</td>
                  <td>{inr(li.claimed_amount)}</td>
                  <td>{li.approved ? "✅ approved" : "❌ rejected"}</td>
                  <td>{li.reason || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {result.financial?.steps && (
        <div className="section-gap">
          <h2>Financial breakdown (ordered)</h2>
          <table>
            <thead>
              <tr><th>Step</th><th>Before</th><th>Adjustment</th><th>After</th></tr>
            </thead>
            <tbody>
              {result.financial.steps.map((s, i) => (
                <tr key={i}>
                  <td>{s.step}<div className="meta" style={{ color: "var(--muted)", fontSize: 11.5 }}>{s.description}</div></td>
                  <td>{inr(s.amount_before)}</td>
                  <td>{Number(s.adjustment) === 0 ? "—" : inr(s.adjustment)}</td>
                  <td>{inr(s.amount_after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function ResultView({ result }) {
  if (!result) {
    return (
      <div className="panel">
        <h2>Decision review</h2>
        <p className="hint">
          Submit a claim (or load a preset like TC001 for a document stop, TC004 for a clean
          approval, TC010 for the network-discount breakdown) and the decision, reasons, and
          full processing trace will appear here.
        </p>
      </div>
    );
  }
  const stopped = result.status === "DOCUMENTS_REQUIRED";
  return (
    <div className="panel">
      <h2>
        Decision review · <code>{result.claim_id}</code>
        {result.persistence && result.persistence !== "ok" && (
          <span className="badge DOCUMENTS_REQUIRED" style={{ marginLeft: 8 }}>persistence degraded</span>
        )}
      </h2>
      {stopped ? <DocumentProblems result={result} /> : <Decision result={result} />}
      <div className="section-gap">
        <h2>Processing trace — every check, in order</h2>
        <TraceTimeline trace={result.trace} />
      </div>
    </div>
  );
}
