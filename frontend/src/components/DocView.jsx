import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "../api";

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
