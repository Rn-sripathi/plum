import { useEffect, useState } from "react";
import { api } from "../api";

export default function ClaimsList({ onSelect, refreshKey }) {
  const [claims, setClaims] = useState([]);

  useEffect(() => {
    api.listClaims().then(setClaims).catch(() => setClaims([]));
  }, [refreshKey]);

  if (!claims.length) return null;
  return (
    <div className="panel section-gap">
      <h2>Recent claims</h2>
      <table>
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
              <td><span className={`badge ${c.status}`}>{c.status.replace("_", " ")}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
