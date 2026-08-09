import { useEffect, useState } from "react";
import { api } from "../api";

/** Thumbnails of files chosen in the form, before submitting. */
export function FilePreviews({ files }) {
  const [urls, setUrls] = useState([]);

  useEffect(() => {
    const made = files.map((file) =>
      file.type.startsWith("image/") ? URL.createObjectURL(file) : null
    );
    setUrls(made);
    // Object URLs hold the file in memory until revoked.
    return () => made.forEach((url) => url && URL.revokeObjectURL(url));
  }, [files]);

  if (!files.length) return null;
  return (
    <div className="thumbs">
      {files.map((file, i) => (
        <figure className="thumb" key={file.name + i}>
          {urls[i] ? (
            <img src={urls[i]} alt={file.name} />
          ) : (
            <div className="thumb-doc">PDF</div>
          )}
          <figcaption title={file.name}>{file.name}</figcaption>
        </figure>
      ))}
    </div>
  );
}

/** Documents attached to a decided claim, fetched from the server. */
export default function DocumentPreview({ claimId, documents }) {
  const [zoomed, setZoomed] = useState(null);
  if (!documents?.length) return null;

  const previewable = documents.filter((d) => d.previewable);
  return (
    <div className="section-gap">
      <h2>Documents submitted</h2>
      {previewable.length === 0 ? (
        <p className="hint">
          These documents were submitted as structured data (eval case), so there are no
          files to display.
        </p>
      ) : (
        <div className="thumbs">
          {previewable.map((doc) => {
            const url = api.documentUrl(claimId, doc.file_id);
            const isPdf = (doc.file_name || "").toLowerCase().endsWith(".pdf");
            return (
              <figure className="thumb" key={doc.file_id}>
                {isPdf ? (
                  <a className="thumb-doc" href={url} target="_blank" rel="noreferrer">
                    PDF
                  </a>
                ) : (
                  <img
                    src={url}
                    alt={doc.file_name || doc.file_id}
                    onClick={() => setZoomed(url)}
                    title="Click to enlarge"
                  />
                )}
                <figcaption title={doc.file_name || doc.file_id}>
                  {doc.doc_type && <span className="doc-type">{doc.doc_type}</span>}
                  {doc.file_name || doc.file_id}
                </figcaption>
              </figure>
            );
          })}
        </div>
      )}

      {zoomed && (
        <div className="lightbox" onClick={() => setZoomed(null)} role="presentation">
          <img src={zoomed} alt="Document" />
          <div className="lightbox-hint">click anywhere to close</div>
        </div>
      )}
    </div>
  );
}
