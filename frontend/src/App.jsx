import { useEffect, useState } from "react";
import Analytics from "./components/Analytics";
import { api } from "./api";
import ClaimsList from "./components/ClaimsList";
import DocView, { DocsPage } from "./components/DocView";
import Logo from "./components/Logo";
import NavMenu from "./components/NavMenu";
import ResultView from "./components/ResultView";
import StatusChip from "./components/StatusChip";
import SubmitForm from "./components/SubmitForm";

/** Two bars, not a glyph swap — so + can rotate into − rather than blink. */
function Sign({ open = false }) {
  return (
    <span className={open ? "nav-sign open" : "nav-sign"} aria-hidden="true">
      <i />
      <i />
    </span>
  );
}

export default function App() {
  const [view, setView] = useState("console");
  const [docSlug, setDocSlug] = useState("architecture");
  const [menuOpen, setMenuOpen] = useState(false);
  const [result, setResult] = useState(null);
  const [liveSteps, setLiveSteps] = useState(null); // null = not streaming
  const [health, setHealth] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, [refreshKey]);

  // The whole page washes warm while the menu is open, as on plumhr.com.
  useEffect(() => {
    document.body.classList.toggle("menu-open", menuOpen);
    return () => document.body.classList.remove("menu-open");
  }, [menuOpen]);

  function go(next) {
    setView(next);
    setMenuOpen(false);
  }

  function openDoc(slug) {
    setDocSlug(slug);
    setView("docs");
    setMenuOpen(false);
  }

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
    <div className="shell" onMouseLeave={() => setMenuOpen(false)}>
      <header className="topbar">
        <div className="brand">
          <Logo />
          <h1>Claims Processing</h1>
        </div>
        <nav className="nav">
          <button
            type="button"
            className={view === "console" ? "nav-link active" : "nav-link"}
            onMouseEnter={() => setMenuOpen(false)}
            onClick={() => go("console")}
          >
            <Sign /> Console
          </button>
          <button
            type="button"
            className={view === "analytics" ? "nav-link active" : "nav-link"}
            onMouseEnter={() => setMenuOpen(false)}
            onClick={() => go("analytics")}
          >
            <Sign /> Analytics
          </button>
          <button
            type="button"
            className={view === "claims" ? "nav-link active" : "nav-link"}
            onMouseEnter={() => setMenuOpen(false)}
            onClick={() => go("claims")}
          >
            <Sign /> Recent claims
          </button>
          <button
            type="button"
            className={view === "eval" ? "nav-link active" : "nav-link"}
            onMouseEnter={() => setMenuOpen(false)}
            onClick={() => go("eval")}
          >
            <Sign /> Eval report
          </button>
          <button
            type="button"
            className={view === "docs" ? "nav-link active" : "nav-link"}
            aria-expanded={menuOpen}
            onMouseEnter={() => setMenuOpen(true)}
            onClick={() => setMenuOpen((o) => !o)}
          >
            <Sign open={menuOpen} /> Docs
          </button>
        </nav>
        <StatusChip health={health} />
      </header>

      <NavMenu open={menuOpen} onPick={openDoc} />

      {view === "console" ? (
        <main className="layout">
          <SubmitForm onResult={handleResult} onStep={handleStep} onStart={handleStart} />
          <ResultView result={result} liveSteps={liveSteps} />
        </main>
      ) : view === "analytics" ? (
        <main>
          <Analytics />
        </main>
      ) : view === "claims" ? (
        <main className="layout claims-layout">
          <ClaimsList onSelect={handleSelect} refreshKey={refreshKey} showEmpty />
          <ResultView
            result={result}
            liveSteps={null}
            emptyHint="Pick a claim on the left to read its decision, documents, and full processing trace."
          />
        </main>
      ) : (
        <main className="doc-layout">
          {view === "docs" ? (
            <DocsPage slug={docSlug} onSelect={setDocSlug} />
          ) : (
            <DocView slug={view} />
          )}
        </main>
      )}
    </div>
  );
}
