import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import TraceTimeline from "./TraceTimeline";

/** Openers that show what the assistant is for without a paragraph of prose. */
const STARTERS = [
  "Is teeth whitening covered under dental?",
  "What is the per-claim limit?",
  "Which claims were rejected for a waiting period?",
  "What is our payout ratio, and which stage costs the most time?",
];

/** A citation is a pointer, not a footnote: policy refs read as paths into
 *  policy_terms.json, claim refs as claim ids. Showing the raw ref is the
 *  point — it is checkable. */
function Citations({ citations }) {
  if (!citations.length) return null;
  return (
    <div className="cites">
      {citations.map((c) => (
        <span key={`${c.kind}:${c.ref}`} className={`cite ${c.kind}`} title={c.detail || c.kind}>
          {c.ref}
        </span>
      ))}
    </div>
  );
}

function Turn({ turn }) {
  if (turn.role === "user") {
    return <div className="turn user">{turn.content}</div>;
  }
  const { answer, pending } = turn;
  if (pending) {
    return (
      <div className="turn assistant">
        <div className="thinking">
          <span className="dots" /> {turn.steps.length
            ? turn.steps[turn.steps.length - 1].action.replace("retrieve: ", "reading ")
            : "thinking"}
        </div>
        {turn.steps.length > 0 && <TraceTimeline trace={{ steps: turn.steps }} live />}
      </div>
    );
  }
  return (
    <div className="turn assistant">
      {/* An answer the gates rejected is never shown as though it were sourced. */}
      {!answer.grounded && (
        <div className="ungrounded">
          <b>Not grounded</b> — showing retrieved material instead of an explanation.
          {answer.refusals.length > 0 && <div className="why">{answer.refusals.join(" · ")}</div>}
        </div>
      )}
      <div className="said">{answer.answer}</div>
      <Citations citations={answer.citations} />
      {answer.degraded_components.length > 0 && (
        <div className="degraded-note">
          Degraded: {answer.degraded_components.join(", ")} — answered from the fallback source.
        </div>
      )}
      {answer.trace?.steps?.length > 0 && (
        <details className="turn-trace">
          <summary>How this was answered ({answer.trace.steps.length} steps)</summary>
          <TraceTimeline trace={answer.trace} />
        </details>
      )}
    </div>
  );
}

export default function Assistant({ claimId = null }) {
  const [turns, setTurns] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [available, setAvailable] = useState(null);
  const endRef = useRef(null);

  useEffect(() => {
    api.health().then((h) => setAvailable(h.llm === "configured")).catch(() => setAvailable(false));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  async function send(text) {
    const question = text.trim();
    if (!question || busy) return;
    setDraft("");
    setError(null);
    setBusy(true);

    // The server keeps no session, so the history it should consider is whatever
    // we post — built from the turns already on screen.
    const history = [
      ...turns.filter((t) => t.role === "user" || t.answer).map((t) => ({
        role: t.role,
        content: t.role === "user" ? t.content : t.answer.answer,
      })),
      { role: "user", content: question },
    ];
    setTurns((prev) => [
      ...prev,
      { role: "user", content: question },
      { role: "assistant", pending: true, steps: [] },
    ]);

    const onStep = (step) =>
      setTurns((prev) =>
        prev.map((t, i) => (i === prev.length - 1 ? { ...t, steps: [...t.steps, step] } : t)),
      );

    try {
      const answer = await api.assistantChat({ messages: history, claim_id: claimId }, onStep);
      setTurns((prev) =>
        prev.map((t, i) => (i === prev.length - 1 ? { role: "assistant", answer } : t)),
      );
    } catch (err) {
      setError(err.message);
      setTurns((prev) => prev.slice(0, -1));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="assistant">
      <div className="panel assistant-panel">
        <h2>Assistant</h2>
        <p className="hint">
          Ask why a claim was decided as it was, what the policy says, or how the portfolio
          looks. It explains decisions and cites the clause behind every answer — it does
          not make decisions, and it will not predict an amount.
          {available === false && (
            <>
              {" "}
              <b>No language model is configured</b>, so answers are retrieved clauses rather
              than explanations.
            </>
          )}
        </p>

        {turns.length === 0 && (
          <div className="starters">
            {STARTERS.map((s) => (
              <button key={s} type="button" className="starter" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        )}

        <div className="turns">
          {turns.map((turn, i) => (
            <Turn key={i} turn={turn} />
          ))}
          <div ref={endRef} />
        </div>

        {error && <div className="error-box section-gap">{error}</div>}

        <form
          className="ask"
          onSubmit={(e) => {
            e.preventDefault();
            send(draft);
          }}
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={claimId ? `Ask about ${claimId}…` : "Ask about a claim, the policy, or the portfolio…"}
            disabled={busy}
          />
          <button type="submit" disabled={busy || !draft.trim()}>
            {busy ? "Asking…" : "Ask"}
          </button>
        </form>
      </div>
    </div>
  );
}
