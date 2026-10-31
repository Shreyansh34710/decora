import React, { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const MAX_FILE_BYTES = 2 * 1024 * 1024;

const statusLabels = {
  accepted: "Accepted",
  rejected: "Rejected",
  unresolved: "Unresolved",
  contested: "Contested",
};

function statusCount(decisions, status) {
  return decisions.filter((decision) => decision.status === status).length;
}

function extractError(error) {
  if (typeof error?.detail === "string") return error.detail;
  if (Array.isArray(error?.detail)) return error.detail.map((item) => item.msg).join(" ");
  return "The discussion could not be analyzed. Please try again.";
}

function Evidence({ evidence }) {
  return (
    <li className="evidence-item">
      <blockquote>“{evidence.quote}”</blockquote>
      <div className="source-meta">
        <span>{evidence.segment_id}</span>
        {evidence.author && <span>{evidence.author}</span>}
        {evidence.timestamp && <span>{evidence.timestamp}</span>}
        {evidence.source_url && <a href={evidence.source_url} target="_blank" rel="noreferrer">Open source</a>}
        <span className="verified-source">Verified source</span>
      </div>
    </li>
  );
}

function DecisionCard({ decision }) {
  const [expanded, setExpanded] = useState(false);
  const label = statusLabels[decision.status] || decision.status;
  return (
    <article className={`decision-card ${decision.status}`}>
      <div className="card-header">
        <span className={`status status-${decision.status}`}>{label}</span>
        <span className={decision.verified ? "verification verified" : "verification unverified"}>
          {decision.verified ? "Evidence verified" : "Evidence unverified"}
        </span>
      </div>
      <h3>{decision.proposal}</h3>
      <dl className="decision-detail">
        <div><dt>Outcome basis</dt><dd>{decision.outcome_basis.replaceAll("_", " ")}</dd></div>
        <div><dt>Evidence</dt><dd>{decision.evidence.length} supporting message{decision.evidence.length === 1 ? "" : "s"}</dd></div>
      </dl>
      {decision.reason && <p className="reason"><span>Recovered reasoning</span>{decision.reason}</p>}
      {!decision.verified && <p className="notice">The model returned evidence that could not be verified against the imported source.</p>}
      <button className="evidence-toggle" type="button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
        {expanded ? "Hide source evidence" : "Inspect source evidence"}
      </button>
      {expanded && (
        <section className="evidence-panel" aria-label="Original source evidence">
          <p className="evidence-note">These are original discussion messages. Proposal, status, and reasoning above are AI-extracted.</p>
          {decision.evidence.length ? <ul>{decision.evidence.map((evidence, index) => <Evidence evidence={evidence} key={`${evidence.segment_id}-${index}`} />)}</ul> : <p>No verified supporting messages were returned.</p>}
        </section>
      )}
    </article>
  );
}

function App() {
  const [title, setTitle] = useState("Untitled discussion");
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [fileName, setFileName] = useState("");

  const counts = useMemo(() => {
    const decisions = result?.decisions || [];
    return ["accepted", "rejected", "unresolved", "contested"].map((status) => ({ status, count: statusCount(decisions, status) }));
  }, [result]);

  async function handleFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".txt") || file.type && !file.type.startsWith("text/")) {
      setError("Choose a plain-text (.txt) discussion file.");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError("The text file must be 2 MB or smaller.");
      return;
    }
    setText(await file.text());
    setFileName(file.name);
    setError("");
    if (title === "Untitled discussion") setTitle(file.name.replace(/\.txt$/i, ""));
  }

  async function analyze(event) {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) {
      setError("Paste a discussion or choose a .txt file before analyzing.");
      return;
    }
    if (trimmed.length < 20) {
      setError("The discussion must contain at least 20 characters.");
      return;
    }
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const response = await fetch(`${API_BASE_URL}/api/extract`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title.trim() || "Untitled discussion", text: trimmed }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw payload;
      setResult(payload);
    } catch (requestError) {
      setError(extractError(requestError));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <header className="site-header">
        <a className="brand" href="#workspace"><span className="brand-mark">D</span><span>Decora</span></a>
        <span className="model-badge">Local Qwen3 inference</span>
      </header>
      <section className="hero" id="workspace">
        <p className="eyebrow">Engineering decision recovery</p>
        <h1>Recover the decisions<br />behind the code.</h1>
        <p className="intro">Import a technical discussion. Decora finds proposals, outcomes, and the exact messages that support them.</p>
      </section>
      <section className="workspace" aria-label="Discussion analysis workspace">
        <form onSubmit={analyze}>
          <div className="form-row">
            <label>Discussion title<input value={title} onChange={(event) => setTitle(event.target.value)} maxLength="200" /></label>
            <label className="file-input"><span>{fileName || "Import .txt file"}</span><input type="file" accept=".txt,text/plain" onChange={handleFile} /></label>
          </div>
          <label className="discussion-label">Raw discussion<textarea value={text} onChange={(event) => setText(event.target.value)} placeholder={"Alice: I propose using PostgreSQL for the service.\n\nBob: We need relational constraints for these entities."} rows="11" /></label>
          <div className="form-footer"><span>Messages are processed in chronological order. Uploaded files stay in your browser.</span><button type="submit" disabled={loading}>{loading ? "Analyzing with Qwen3…" : "Analyze discussion"}</button></div>
        </form>
        {error && <p className="error" role="alert">{error}</p>}
      </section>
      {result && <section className="results" aria-live="polite">
        <div className="results-heading"><div><p className="eyebrow">Extraction result</p><h2>{result.discussion_title}</h2><p>{result.total_messages} source messages · {result.model}</p></div><span className="verification-summary">{result.verified_decisions}/{result.decisions.length} decisions verified</span></div>
        <div className="summary-grid">{counts.map(({ status, count }) => <div className={`summary ${status}`} key={status}><strong>{count}</strong><span>{statusLabels[status]}</span></div>)}</div>
        {result.decisions.length ? <div className="decision-grid">{result.decisions.map((decision) => <DecisionCard decision={decision} key={decision.decision_id} />)}</div> : <div className="empty-result"><h3>No decisions recovered</h3><p>The model completed analysis but did not find a supported engineering decision in this discussion.</p></div>}
      </section>}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);
