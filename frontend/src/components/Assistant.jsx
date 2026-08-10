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

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path
        d="M12 19V6M12 5l-6 6M12 5l6 6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M15 5.5A2.5 2.5 0 0012.5 3H6.5A2.5 2.5 0 004 5.5v6A2.5 2.5 0 006.5 14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function RetryIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
      <path d="M20 12a8 8 0 11-2.34-5.66M20 4v4h-4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

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

/**
 * The composer: one rounded field that grows with the text, with its controls
 * inside it — the model in use on the left of the send button, so the reader can
 * see whether they are getting explanations or retrieved clauses.
 */
function Composer({ value, onChange, onSubmit, busy, placeholder, model }) {
  // Grown by row count rather than by measuring scrollHeight: measuring an
  // empty textarea after resetting its height reported the max, which opened
  // the composer at full height before a word was typed.
  const rows = Math.min(
    8,
    value.split("\n").length + Math.floor(value.replace(/\n/g, "").length / 88),
  );

  return (
    <form
      className={rows > 1 ? "composer tall" : "composer"}
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <textarea
        rows={Math.max(1, rows)}
        value={value}
        placeholder={placeholder}
        disabled={busy}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          // Enter sends; Shift+Enter is a newline, as everywhere else.
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSubmit();
          }
        }}
      />
      <div className="composer-row">
        <span className={`model ${model.ok ? "ok" : "degraded"}`} title={model.title}>
          <i /> {model.label}
        </span>
        <button type="submit" className="send" disabled={busy || !value.trim()} aria-label="Ask">
          <SendIcon />
        </button>
      </div>
    </form>
  );
}

function Answer({ turn, onRetry }) {
  const { answer } = turn;
  const [copied, setCopied] = useState(false);

  return (
    <div className="msg assistant">
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
      <div className="msg-actions">
        <button
          type="button"
          title="Copy answer"
          onClick={() => {
            navigator.clipboard?.writeText(answer.answer);
            setCopied(true);
            setTimeout(() => setCopied(false), 1400);
          }}
        >
          <CopyIcon /> {copied ? "Copied" : "Copy"}
        </button>
        <button type="button" title="Ask again" onClick={onRetry}>
          <RetryIcon /> Retry
        </button>
        {answer.trace?.steps?.length > 0 && (
          <details className="msg-trace">
            <summary>How this was answered ({answer.trace.steps.length} steps)</summary>
            <TraceTimeline trace={answer.trace} />
          </details>
        )}
      </div>
    </div>
  );
}

export default function Assistant({ claimId = null }) {
  const [turns, setTurns] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [hasModel, setHasModel] = useState(true);
  const endRef = useRef(null);

  useEffect(() => {
    api.health().then((h) => setHasModel(h.llm === "configured")).catch(() => setHasModel(false));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const model = hasModel
    ? { ok: true, label: "GPT-4o", title: "Answers are explained and cited." }
    : {
        ok: false,
        label: "Deterministic",
        title: "No language model configured — answers are retrieved clauses, not explanations.",
      };

  async function send(text) {
    const question = text.trim();
    if (!question || busy) return;
    setDraft("");
    setError(null);
    setBusy(true);

    // The server keeps no session, so the history it should consider is whatever
    // we post — built from the turns already on screen.
    const history = [
      ...turns
        .filter((t) => t.role === "user" || t.answer)
        .map((t) => ({
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

  function retry(index) {
    const question = turns[index - 1]?.content;
    if (question) {
      setTurns((prev) => prev.slice(0, index - 1));
      send(question);
    }
  }

  const composer = (
    <Composer
      value={draft}
      onChange={setDraft}
      onSubmit={() => send(draft)}
      busy={busy}
      model={model}
      placeholder={claimId ? `Ask about ${claimId}…` : "Ask about a claim, the policy, or the portfolio"}
    />
  );
  const disclaimer = (
    <p className="chat-note">
      Explains decisions and cites the clause behind every answer. It does not decide claims,
      and will not predict an amount.
    </p>
  );

  // Nothing asked yet: the greeting and the composer sit together in the middle,
  // as the whole point of the view is the one thing you do with it.
  if (turns.length === 0) {
    return (
      <div className="chat">
        <div className="chat-hero">
          <h1 className="chat-greeting">What do you need to know?</h1>
          {composer}
          <div className="starters">
            {STARTERS.map((s) => (
              <button key={s} type="button" className="starter" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
          {error && <div className="error-box">{error}</div>}
          {disclaimer}
        </div>
      </div>
    );
  }

  return (
    <div className="chat">
      <div className="chat-stream">
        <div className="chat-column">
          {turns.map((turn, i) =>
            turn.role === "user" ? (
              <div className="msg user" key={i}>
                {turn.content}
              </div>
            ) : turn.pending ? (
              <div className="msg assistant" key={i}>
                <div className="thinking">
                  <span className="dots" />{" "}
                  {turn.steps.length
                    ? turn.steps[turn.steps.length - 1].action.replace("retrieve: ", "reading ")
                    : "thinking"}
                </div>
                {turn.steps.length > 0 && <TraceTimeline trace={{ steps: turn.steps }} live />}
              </div>
            ) : (
              <Answer key={i} turn={turn} onRetry={() => retry(i)} />
            ),
          )}
          <div ref={endRef} />
        </div>
      </div>
      <div className="chat-foot">
        <div className="chat-column">
          {error && <div className="error-box">{error}</div>}
          {composer}
          {disclaimer}
        </div>
      </div>
    </div>
  );
}
