export default function TraceTimeline({ trace }) {
  if (!trace?.steps?.length) return null;
  return (
    <div className="trace">
      {trace.steps.map((s) => (
        <div className="step" key={s.seq}>
          <div className="seq">{s.seq}</div>
          <div className={`outcome ${s.outcome}`}>{s.outcome}</div>
          <div className="body">
            <div className="component">
              {s.component} · <span style={{ fontWeight: 400 }}>{s.action}</span>
            </div>
            <div className="detail">{s.detail}</div>
            {(s.rule_ref || s.confidence_delta !== 0) && (
              <div className="meta">
                {s.rule_ref && <>rule: <code>{s.rule_ref}</code></>}
                {s.rule_ref && s.confidence_delta !== 0 && " · "}
                {s.confidence_delta !== 0 && <>confidence {s.confidence_delta > 0 ? "+" : ""}{s.confidence_delta}</>}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
