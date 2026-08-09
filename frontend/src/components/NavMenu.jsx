import { api } from "../api";
import { DOC_TABS } from "./DocView";

/**
 * The expanding nav panel. Opens on hover (and on click, so it works on
 * touch and by keyboard), with the sign flipping + → − like Plum's menu.
 */
export default function NavMenu({ open, onPick }) {
  if (!open) return null;
  return (
    <div className="mega">
      <div className="mega-inner">
        <ul className="mega-list">
          {DOC_TABS.map((tab) => (
            <li key={tab.slug}>
              <button type="button" onClick={() => onPick(tab.slug)}>
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
        <p className="mega-note">
          Everything an evaluator needs, served from the running system: the
          design and its trade-offs, the contract for each component, and the
          live OpenAPI reference.
        </p>
      </div>
    </div>
  );
}
