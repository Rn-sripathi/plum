import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api";

/** The project documents, also listed in the nav's Docs menu. */
export const DOC_TABS = [
  { slug: "architecture", label: "Architecture" },
  { slug: "contracts", label: "Contracts" },
  { slug: "assumptions", label: "Assumptions" },
];

export function DocsPage({ slug, onSelect }) {
  return (
    <>
      <div className="doc-tabs">
        {DOC_TABS.map((tab) => (
          <button
            key={tab.slug}
            type="button"
            className={slug === tab.slug ? "doc-tab active" : "doc-tab"}
            onClick={() => onSelect(tab.slug)}
          >
            {tab.label}
          </button>
        ))}
        <a className="doc-tab" href={api.apiDocsUrl()} target="_blank" rel="noreferrer">
          API reference ↗
        </a>
      </div>
      <DocView slug={slug} />
    </>
  );
}

/** Renders a project document so the deployed URL carries its own evidence. */
export default function DocView({ slug }) {
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setDoc(null);
    setError(null);
    api.getDoc(slug).then(setDoc).catch((e) => setError(e.message));
  }, [slug]);

  if (error) return <div className="panel"><div className="error-box">{error}</div></div>;
  if (!doc) return <div className="panel"><p className="hint">Loading…</p></div>;

  return (
    <div className="panel doc">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{doc.markdown}</ReactMarkdown>
    </div>
  );
}
