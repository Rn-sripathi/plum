import { api } from "../api";
import { DOC_TABS } from "./DocView";
import StatusChip from "./StatusChip";

/**
 * The nav as a drawer, for widths where six uppercase labels and a status chip
 * cannot share one bar.
 *
 * Same destinations as the desktop bar, plus the documents that sit behind Docs'
 * hover menu there — a hover is not available on touch, so they are listed
 * outright. The status chip comes along because the bar keeps only its dot at
 * these widths, and "which components are degraded" is worth a full sentence
 * somewhere.
 */
export default function MobileNav({ open, views, view, health, onGo, onPickDoc }) {
  if (!open) return null;
  return (
    <div className="drawer">
      <ul className="mega-list">
        {views.map((v) => (
          <li key={v.id}>
            <button
              type="button"
              className={view === v.id ? "active" : undefined}
              onClick={() => onGo(v.id)}
            >
              {v.label}
            </button>
          </li>
        ))}
      </ul>

      <div className="drawer-heading">Project documents</div>
      <ul className="mega-list">
        {DOC_TABS.map((tab) => (
          <li key={tab.slug}>
            <button type="button" onClick={() => onPickDoc(tab.slug)}>
              {tab.label}
            </button>
          </li>
        ))}
        <li>
          <a href={api.apiDocsUrl()} target="_blank" rel="noreferrer">
            API reference ↗
          </a>
        </li>
      </ul>

      <div className="drawer-status">
        <StatusChip health={health} />
      </div>
    </div>
  );
}
