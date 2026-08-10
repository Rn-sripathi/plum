import { useEffect, useState } from "react";

/**
 * Renders a mermaid diagram from a fenced ```mermaid block.
 *
 * mermaid is imported dynamically: it is by far the heaviest dependency here and
 * only the docs pages need it, so the console never pays for it. Until it
 * resolves — and if it fails outright — the diagram source is shown as text,
 * because a reader can follow a flowchart in source form but not a blank space.
 */
export default function Mermaid({ chart }) {
  const [svg, setSvg] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    setSvg(null);
    setFailed(false);

    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          // "base" plus explicit variables, so diagrams wear the product's
          // palette rather than mermaid's default lavender.
          theme: "base",
          // Default spacing turns a twenty-node flow into a sparse ribbon;
          // tightening the ranks keeps the whole path on one screen.
          flowchart: { nodeSpacing: 24, rankSpacing: 34, padding: 10, useMaxWidth: true },
          themeVariables: {
            fontFamily: '"DM Sans", "Segoe UI", system-ui, sans-serif',
            fontSize: "14px",
            primaryColor: "#fdefe7",
            primaryTextColor: "#2c0a26",
            primaryBorderColor: "#e8cdc2",
            secondaryColor: "#f4f5fb",
            tertiaryColor: "#ffffff",
            lineColor: "#b9a4ad",
            textColor: "#34303a",
            edgeLabelBackground: "#fdfbfa",
          },
        });
        // A fresh id per render: mermaid keys its temporary DOM on it.
        const { svg: rendered } = await mermaid.render(
          `mmd-${Math.random().toString(36).slice(2, 9)}`,
          chart,
        );
        if (alive) setSvg(rendered);
      } catch {
        if (alive) setFailed(true);
      }
    })();

    return () => {
      alive = false;
    };
  }, [chart]);

  if (failed) return <pre className="diagram-source">{chart}</pre>;
  if (!svg) return <pre className="diagram-source loading">{chart}</pre>;
  // Wide diagrams scroll inside their own box; the page never scrolls sideways.
  return (
    <div className="diagram" role="img" dangerouslySetInnerHTML={{ __html: svg }} />
  );
}
