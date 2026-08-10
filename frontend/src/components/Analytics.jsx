import { useEffect, useState } from "react";
import { api } from "../api";

const inr = (v) => `₹${Number(v).toLocaleString("en-IN")}`;
const pct = (v) => `${Math.round(v * 100)}%`;
// "0ms" would read as no time at all; a deterministic check really is sub-
// millisecond, and saying so is the point of this chart.
const ms = (v) => {
  if (v >= 1000) return `${(v / 1000).toFixed(1)}s`;
  return v >= 1 ? `${Math.round(v)}ms` : "<1ms";
};

/** Decision outcomes mean good/bad, so they wear status tokens, not series
 *  hues — and status always ships with a label, never colour alone. The stack
 *  order is fixed: re-ordering put amber next to red, which collapses to
 *  ΔE 2.3 under deuteranopia. */
const STATUS = {
  APPROVED: { label: "Approved", fill: "var(--chart-good)" },
  PARTIAL: { label: "Partial", fill: "var(--chart-warning)" },
  REJECTED: { label: "Rejected", fill: "var(--chart-critical)" },
  MANUAL_REVIEW: { label: "Manual review", fill: "var(--chart-info)" },
  DOCUMENTS_REQUIRED: { label: "Stopped — documents", fill: "var(--chart-neutral)" },
};

const KIND_LABEL = {
  WRONG_TYPE: "Wrong document type",
  UNREADABLE: "Could not be read",
  PATIENT_MISMATCH: "Different patients",
  MISSING_REQUIRED: "Document missing",
  UNCLASSIFIED: "Type undetermined",
};

function Tile({ label, value, note }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {note && <div className="tile-note">{note}</div>}
    </div>
  );
}

/** Part-to-whole across five states. Segments are separated by a 2px surface
 *  gap rather than a stroke, and the legend carries every count so identity
 *  and value never rest on colour. */
function DecisionMix({ mix, total }) {
  const present = mix.filter((m) => m.count > 0);
  return (
    <section className="card">
      <h3>Decision mix</h3>
      <p className="card-sub">How {total} claims resolved.</p>
      <div className="stack" role="img" aria-label="Decision mix by count">
        {present.map((m) => {
          const share = m.count / total;
          return (
            <div
              key={m.status}
              className="stack-seg"
              style={{ width: `${share * 100}%`, background: STATUS[m.status].fill }}
              title={`${STATUS[m.status].label}: ${m.count} of ${total} (${pct(share)})`}
            >
              {/* Only label a segment wide enough to hold the text; the legend
                  carries the rest rather than clipping it. */}
              {share >= 0.1 && <span className="stack-label">{m.count}</span>}
            </div>
          );
        })}
      </div>
      <ul className="legend">
        {present.map((m) => (
          <li key={m.status}>
            <i style={{ background: STATUS[m.status].fill }} />
            {STATUS[m.status].label}
            <b>{m.count}</b>
            <span className="legend-share">{pct(m.count / total)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** A single ratio against its ceiling: a meter, not a two-slice pie. The track
 *  is a lighter step of the same ramp so the state reads across the whole bar. */
function Payout({ money, decided }) {
  if (money.payout_ratio === null) return null;
  return (
    <section className="card">
      <h3>Payout ratio</h3>
      <p className="card-sub">
        Of every rupee claimed across {decided} decided claims, what the policy paid.
      </p>
      <div className="meter" title={`${inr(money.approved)} approved of ${inr(money.claimed)} claimed`}>
        <div className="meter-fill" style={{ width: pct(money.payout_ratio) }} />
      </div>
      <div className="meter-scale">
        <b>{pct(money.payout_ratio)}</b>
        <span>
          {inr(money.approved)} approved · {inr(money.claimed)} claimed
        </span>
      </div>
      <p className="card-foot">
        Not a dial the system turns — it is what co-pay, sub-limits and exclusions add
        up to.
      </p>
    </section>
  );
}

/** Ordered buckets, so colour carries the order: one hue, light → dark. */
function Confidence({ confidence, decided }) {
  const bins = confidence.distribution;
  const peak = Math.max(...bins.map((b) => b.count), 1);
  return (
    <section className="card">
      <h3>Confidence distribution</h3>
      <p className="card-sub">
        Where {decided} decisions landed. {confidence.manual_review} recommended for
        manual review.
      </p>
      <div className="columns">
        {bins.map((b, i) => (
          <div className="column" key={b.bin}>
            <div className="column-value">{b.count || ""}</div>
            <div className="column-track">
              <div
                className="column-fill"
                style={{
                  height: `${(b.count / peak) * 100}%`,
                  background: `var(--seq-${i + 1})`,
                }}
                title={`${b.count} claim(s) at confidence ${b.bin}`}
              />
            </div>
            <div className="column-tick">{b.bin}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

/** Nominal categories: every bar takes the same hue. Colouring them by value
 *  would spend the identity channel re-encoding what bar length already says. */
function Bars({ title, sub, rows, foot }) {
  if (!rows.length) return null;
  const peak = Math.max(...rows.map((r) => r.value), 1);
  return (
    <section className="card">
      <h3>{title}</h3>
      <p className="card-sub">{sub}</p>
      <div className="bars">
        {rows.map((r) => (
          <div className="bar-row" key={r.label}>
            <div className="bar-label" title={r.label}>
              {r.label}
            </div>
            <div className="bar-track">
              <div
                className="bar-fill"
                style={{ width: `${(r.value / peak) * 100}%` }}
                title={r.title || `${r.label}: ${r.display}`}
              />
            </div>
            <div className="bar-value">{r.display}</div>
          </div>
        ))}
      </div>
      {foot && <p className="card-foot">{foot}</p>}
    </section>
  );
}

export default function Analytics() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.analytics().then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="panel"><div className="error-box">{error}</div></div>;
  if (!data) return <div className="panel"><p className="hint">Loading…</p></div>;
  if (!data.available) {
    return (
      <div className="panel">
        <h2>Portfolio</h2>
        <div className="error-box">
          The claim store is unreachable, so there are no figures to show. Decisions are
          still being made — persistence degrades independently. ({data.reason})
        </div>
      </div>
    );
  }
  if (!data.total) {
    return (
      <div className="panel">
        <h2>Portfolio</h2>
        <p className="hint">
          No claims yet. Submit one from the console and these figures start filling in.
        </p>
      </div>
    );
  }

  const { total, decided, stopped, money, confidence, stops, timing, degraded, by_category } = data;
  const slowest = timing[0];

  return (
    <div className="analytics">
      <div className="tiles">
        <Tile
          label="Claims processed"
          value={total.toLocaleString("en-IN")}
          /* Say "all of them" when nothing was truncated — quoting a 500-claim
             window over 93 claims implies data that is not there. */
          note={total >= data.window ? `most recent ${data.window}` : "all stored claims"}
        />
        <Tile
          label="Reached a decision"
          value={pct(decided / total)}
          note={`${stopped} handed back for documents`}
        />
        <Tile label="Approved" value={inr(money.approved)} note={`of ${inr(money.claimed)} claimed`} />
        <Tile
          label="Mean confidence"
          value={confidence.mean === null ? "—" : confidence.mean.toFixed(2)}
          note={`${confidence.manual_review} flagged for review`}
        />
      </div>

      <div className="analytics-grid">
        <DecisionMix mix={data.decision_mix} total={total} />
        <Payout money={money} decided={decided} />
        <Confidence confidence={confidence} decided={decided} />
        <Bars
          title="Where claims stop"
          sub={`Why ${stopped} claims were handed back before any decision.`}
          rows={stops.map((s) => ({
            label: KIND_LABEL[s.kind] || s.kind,
            value: s.count,
            display: String(s.count),
            title: `${s.kind}: ${s.count} claim(s)`,
          }))}
          foot="Every one of these is a claim the member can fix, not a rejection."
        />
        <Bars
          title="Where a claim's time goes"
          sub="Mean per claim, for the claims each stage ran in."
          rows={timing.map((t) => ({
            label: t.component.replace(/_/g, " "),
            value: t.per_claim_ms,
            display: ms(t.per_claim_ms),
            title: `${t.component}: ${ms(t.per_claim_ms)} per claim over ${t.claims} claim(s), ${t.steps} step(s)`,
          }))}
          foot={
            slowest
              ? `Everything expensive leaves the process: the costliest stage is ${slowest.component.replace(/_/g, " ")} at ${ms(slowest.per_claim_ms)} per claim, while the deterministic rules engine decides in under a millisecond.`
              : null
          }
        />
        <Bars
          title="Claims by treatment type"
          sub="Volume per policy category."
          rows={by_category.map((c) => ({
            label: c.category.replace(/_/g, " ").toLowerCase(),
            value: c.count,
            display: String(c.count),
          }))}
        />
      </div>

      {degraded.length > 0 && (
        <section className="card">
          <h3>Degraded runs</h3>
          <p className="card-sub">
            Claims decided with a component missing. Each still produced a decision, at
            reduced confidence.
          </p>
          <ul className="legend">
            {degraded.map((d) => (
              <li key={d.component}>
                <i style={{ background: "var(--chart-warning)" }} />
                {d.component.replace(/_/g, " ")}
                <b>{d.runs}</b>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
