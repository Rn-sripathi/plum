import { useEffect, useState } from "react";
import { api } from "../api";

export default function ClaimsList({ onSelect, refreshKey, showEmpty = false }) {
  const [claims, setClaims] = useState([]);

  useEffect(() => {
    api.listClaims().then(setClaims).catch(() => setClaims([]));
  }, [refreshKey]);

  if (!claims.length) {
    // Inline on the console there is nothing to say; as a view of its own,
    // rendering nothing would leave the page blank.
    if (!showEmpty) return null;
    return (
      <div className="panel">
        <h2>Recent claims</h2>
        <p className="hint">
          No claims yet. Submit one from the console and it will appear here with its
          decision and trace.
        </p>
      </div>
    );
  }
  return (
    <div className="panel">
      <h2>Recent claims</h2>
      <div className="table-wrap">
        <table className="claims">
          <thead>
            <tr><th>Claim</th><th>Member</th><th>Category</th><th>Status</th></tr>
          </thead>
          <tbody>
            {claims.map((c) => (
              <tr
                key={c.claim_id}
                className="clickable"
                onClick={() =>
                  api.getClaim(c.claim_id).then((rec) => onSelect({ ...rec.result, persistence: "ok" }))
                }
              >
                <td><code>{c.claim_id}</code></td>
                <td>{c.member_id}</td>
                <td>{c.category}</td>
                <td><span className={`badge ${c.status}`}>{c.status.replaceAll("_", " ")}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
