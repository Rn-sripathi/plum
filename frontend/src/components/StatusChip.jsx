/**
 * Compact component status. The full detail belongs on hover, not across the
 * whole header — a wall of text there pushed the nav onto two lines.
 */
const DEGRADED = /unreachable|unavailable|not ingested|failed/i;

export default function StatusChip({ health }) {
  if (!health) {
    return (
      <span
        className="status down"
        title="Start it with: uv run fastapi dev app/main.py (from backend/)"
      >
        <i /> backend offline
      </span>
    );
  }

  const parts = [
    ["store", health.store],
    ["llm", health.llm],
    ["index", health.semantic_index],
    ["graph", health.policy_graph],
  ];
  const degraded = parts.filter(([, value]) => DEGRADED.test(value));
  const detail = parts.map(([name, value]) => `${name}: ${value}`).join("\n");

  return (
    <span
      className={degraded.length ? "status warn" : "status ok"}
      title={`${health.policy}\n\n${detail}`}
    >
      <i />
      {degraded.length
        ? `${degraded.map(([name]) => name).join(", ")} degraded`
        : "all systems healthy"}
    </span>
  );
}
