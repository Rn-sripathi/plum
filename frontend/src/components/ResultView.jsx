import { useEffect, useState } from "react";
import DocumentPreview from "./DocumentPreview";
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
          {/* Four columns of prose do not compress to a phone's width; the
              table keeps its shape and scrolls inside the panel instead. */}
          <div className="table-wrap">
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
        </div>
      )}

      {result.financial?.steps && (
        <div className="section-gap">
          <h2>Financial breakdown (ordered)</h2>
          <div className="table-wrap">
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
        </div>
      )}
    </>
  );
}

/**
 * What the pipeline is doing, while it is doing it.
 *
 * The confidence figure is shown as the running adjustment rather than an
 * absolute score: the starting value is the synthesizer's to decide, and
 * duplicating it here would put a second copy of a backend rule in the UI.
 * Watching penalties arrive is the informative part either way.
 */
function LiveProgress({ steps }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = performance.now();
    const timer = setInterval(() => setElapsed((performance.now() - started) / 1000), 100);
    return () => clearInterval(timer);
  }, []);

  const current = steps[steps.length - 1];
  const adjustment = steps.reduce((sum, s) => sum + (s.confidence_delta || 0), 0);

  return (
    <div className="live">
      <div className="live-stat">
        <b>{steps.length}</b> check{steps.length === 1 ? "" : "s"}
      </div>
      <div className="live-stat">
        <b>{elapsed.toFixed(1)}s</b> elapsed
      </div>
      {adjustment !== 0 && (
        <div className="live-stat">
          confidence <b className="down">−{Math.abs(adjustment).toFixed(2)}</b>
        </div>
      )}
      {current && (
        <div className="live-now">
          <span className="dots" /> {current.component.replace(/_/g, " ")}
        </div>
      )}
    </div>
  );
}

export default function ResultView({ result, liveSteps, emptyHint }) {
  if (!result && liveSteps) {
    return (
      <div className="panel">
        <h2>
          Deciding<span className="dots" /> — {liveSteps.length} check
          {liveSteps.length === 1 ? "" : "s"} so far
        </h2>
        <p className="hint">
          Each check appears as the pipeline performs it. Nothing is decided until every
          check below has run.
        </p>
        <LiveProgress steps={liveSteps} />
        <TraceTimeline trace={{ steps: liveSteps }} live />
      </div>
    );
  }
  if (!result) {
    return (
      <div className="panel">
        <h2>Decision review</h2>
        <p className="hint">
          {emptyHint || (
            <>
              Submit a claim (or load a preset like TC001 for a document stop, TC004 for a clean
              approval, TC010 for the network-discount breakdown) and the decision, reasons, and
              full processing trace will appear here.
            </>
          )}
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
      <DocumentPreview claimId={result.claim_id} documents={result.documents} />
      <div className="section-gap">
        <h2>Processing trace — every check, in order</h2>
        <TraceTimeline trace={result.trace} />
      </div>
    </div>
  );
}
