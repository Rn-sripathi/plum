import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import { api } from "../api";

/** The project documents, also listed in the nav's Docs menu. */
export const DOC_TABS = [
  { slug: "review", label: "Review guide" },
  { slug: "architecture", label: "Architecture" },
  { slug: "contracts", label: "Contracts" },
  { slug: "assumptions", label: "Assumptions" },
  { slug: "defects", label: "What running it found" },
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
      {/* rehype-raw so the eval report's <details> traces collapse rather than
          printing their own tags. Raw HTML is only safe because the source is
          fixed: the API serves a four-entry allowlist of files from this
          repo's docs/, never an arbitrary path. */}
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
        {doc.markdown}
      </ReactMarkdown>
    </div>
  );
}
