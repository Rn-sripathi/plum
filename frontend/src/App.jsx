import { useEffect, useState } from "react";
import { api } from "./api";
import ClaimsList from "./components/ClaimsList";
import ResultView from "./components/ResultView";
import SubmitForm from "./components/SubmitForm";

export default function App() {
  const [result, setResult] = useState(null);
  const [health, setHealth] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, [refreshKey]);

  function handleResult(r) {
    setResult(r);
    setRefreshKey((k) => k + 1);
  }

  return (
    <>
      <header className="topbar">
        <h1>Plum · Claims Processing</h1>
        {health ? (
          <span className="badge ok">
            {health.policy} · store {health.store} · llm {health.llm}
          </span>
        ) : (
          <span className="badge REJECTED">backend unreachable — start it with: uv run fastapi dev app/main.py</span>
        )}
      </header>
      <main className="layout">
        <div>
          <SubmitForm onResult={handleResult} />
          <ClaimsList onSelect={setResult} refreshKey={refreshKey} />
        </div>
        <ResultView result={result} />
      </main>
    </>
  );
}
