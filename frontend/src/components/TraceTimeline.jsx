/** Formats a step duration for a column you can compare down, not read across. */
function duration(ms) {
  if (ms === null || ms === undefined) return null;
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  if (ms >= 1) return `${Math.round(ms)}ms`;
  return "<1ms";
}

/**
 * The decision trace: every check in order, with what it cost.
 *
 * A step carries more than its outcome — how long it took and how it moved the
 * confidence score — and both are the answer to questions the trace exists to
 * settle: where did the time go, and why is this claim at 0.78. They get
 * columns of their own so they can be scanned vertically.
 *
 * `live` marks the most recent step while the pipeline is still running, so the
 * eye follows the work as it lands.
 */
export default function TraceTimeline({ trace, live = false }) {
  const steps = trace?.steps;
  if (!steps?.length) return null;

  // A component usually records several steps in a row; naming it once per run
  // of steps turns a flat list into the sequence of stages it actually is.
  const timed = steps.filter((s) => s.duration_ms != null);
  const slowest = timed.reduce((a, b) => (b.duration_ms > a.duration_ms ? b : a), timed[0]);
  const total = timed.reduce((sum, s) => sum + s.duration_ms, 0);

  return (
    <div className="trace">
      {steps.map((s, i) => {
        const newStage = i === 0 || s.component !== steps[i - 1].component;
        const ms = duration(s.duration_ms);
        const dominant = s.duration_ms != null && s.duration_ms >= 500;
        return (
          <div key={s.seq}>
            {newStage && <div className="stage">{s.component.replace(/_/g, " ")}</div>}
            <div
              className={
                "step" + (live && i === steps.length - 1 ? " latest" : "")
              }
            >
              <div className="seq">{s.seq}</div>
              <div className={`outcome ${s.outcome}`}>{s.outcome}</div>
              <div className="body">
                <div className="action">{s.action}</div>
                <div className="detail">{s.detail}</div>
                {s.input_summary && <div className="meta">input: {s.input_summary}</div>}
                {s.rule_ref && (
                  <div className="meta">
                    rule <code>{s.rule_ref}</code>
                  </div>
                )}
              </div>
              <div className={dominant ? "took dominant" : "took"} title="time this step took">
                {ms}
              </div>
              <div className="delta">
                {s.confidence_delta !== 0 && (
                  <span className={s.confidence_delta > 0 ? "up" : "down"}>
                    {s.confidence_delta > 0 ? "+" : "−"}
                    {Math.abs(s.confidence_delta).toFixed(2)}
                  </span>
                )}
              </div>
            </div>
          </div>
        );
      })}
      {slowest && (
        <div className="trace-foot">
          {duration(total)} across {timed.length} step{timed.length === 1 ? "" : "s"} · longest{" "}
          {duration(slowest.duration_ms)} in{" "}
          <b>
            {slowest.component.replace(/_/g, " ")} · {slowest.action}
          </b>
          . Which step dominates is worth reading off the trace rather than assuming: the
          calls that leave the process cost seconds, the policy checks cost microseconds.
        </div>
      )}
    </div>
  );
}
