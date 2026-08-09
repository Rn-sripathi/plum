import { useEffect, useState } from "react";
import { api } from "./api";
import ClaimsList from "./components/ClaimsList";
import ResultView from "./components/ResultView";
import SubmitForm from "./components/SubmitForm";

export default function App() {
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
        <h1>Plum · Claims Processing</h1>
        {health ? (
          <span className="badge ok">
            {health.policy} · store {health.store} · llm {health.llm} · index{" "}
            {health.semantic_index} · graph {health.policy_graph}
          </span>
        ) : (
          <span className="badge REJECTED">
            backend unreachable — start it with: uv run fastapi dev app/main.py
          </span>
        )}
      </header>
      <main className="layout">
        <div>
          <SubmitForm onResult={handleResult} onStep={handleStep} onStart={handleStart} />
          <ClaimsList onSelect={handleSelect} refreshKey={refreshKey} />
        </div>
        <ResultView result={result} liveSteps={liveSteps} />
      </main>
    </>
  );
}
