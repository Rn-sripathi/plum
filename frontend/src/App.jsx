import { useEffect, useState } from "react";
import { api } from "./api";
import ClaimsList from "./components/ClaimsList";
import DocView, { DocsPage } from "./components/DocView";
import Logo from "./components/Logo";
import ResultView from "./components/ResultView";
import SubmitForm from "./components/SubmitForm";

const NAV = [
  { id: "console", label: "Console" },
  { id: "eval", label: "Eval report" },
  { id: "docs", label: "Docs" },
];

export default function App() {
  const [view, setView] = useState("console");
  const [result, setResult] = useState(null);
  const [liveSteps, setLiveSteps] = useState(null); // null = not streaming
  const [health, setHealth] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, [refreshKey]);

  function handleStart() {
    setResult(null);
    setLiveSteps([]);
  }

  function handleStep(step) {
    setLiveSteps((steps) => [...(steps || []), step]);
  }

  function handleResult(r) {
    setResult(r);
    setLiveSteps(null);
    setRefreshKey((k) => k + 1);
  }

  function handleSelect(r) {
    setResult(r);
    setLiveSteps(null);
  }

  return (
    <>
      <header className="topbar">
        <Logo />
        <h1>Claims Processing</h1>
        <nav className="nav">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={view === item.id ? "nav-link active" : "nav-link"}
              onClick={() => setView(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        {health ? (
          <span className="badge ok" title="live component status">
            {health.policy} · store {health.store} · llm {health.llm} · index{" "}
            {health.semantic_index} · graph {health.policy_graph}
          </span>
        ) : (
          <span className="badge REJECTED">
            backend unreachable — start it with: uv run fastapi dev app/main.py
          </span>
        )}
      </header>

      {view === "console" ? (
        <main className="layout">
          <div>
            <SubmitForm onResult={handleResult} onStep={handleStep} onStart={handleStart} />
            <ClaimsList onSelect={handleSelect} refreshKey={refreshKey} />
          </div>
          <ResultView result={result} liveSteps={liveSteps} />
        </main>
      ) : (
        <main className="doc-layout">
          {view === "docs" ? <DocsPage /> : <DocView slug={view} />}
        </main>
      )}
    </>
  );
}
