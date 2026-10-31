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

function githubErrorMessage(error) {
  if (error?.status === 429) {
    return `${extractError(error)}${error.retryAfter ? ` Retry after ${error.retryAfter} seconds.` : " Retry after a short wait."}`;
  }
  return extractError(error);
}

function externalHref(value) {
  return typeof value === "string" && /^https?:\/\//i.test(value) ? value : null;
}

function canonicalGitHubRepositoryUrl(value) {
  try {
    const input = value.trim();
    const authority = input.match(/^https:\/\/([^/?#]+)/i)?.[1]?.toLowerCase();
    const url = new URL(input);
    const match = url.pathname.match(/^\/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)\/([A-Za-z0-9][A-Za-z0-9._-]{0,99})\/?$/);
    if (url.protocol !== "https:" || authority !== "github.com" || url.hostname.toLowerCase() !== "github.com" ||
        url.username || url.password || url.port || url.search || url.hash || !match ||
        match[2] === "." || match[2] === "..") return null;
    return `https://github.com/${match[1]}/${match[2]}`;
  } catch {
    return null;
  }
}

function Evidence({ evidence }) {
  const sourceHref = externalHref(evidence.source_url);
  return (
    <li className="evidence-item">
      <blockquote>“{evidence.quote}”</blockquote>
      <div className="source-meta">
        <span>{evidence.segment_id}</span>
        {evidence.author && <span>{evidence.author}</span>}
        {evidence.timestamp && <span>{evidence.timestamp}</span>}
        {sourceHref && <a href={sourceHref} target="_blank" rel="noreferrer">Open source</a>}
        <span className={evidence.quote_verified ? "verified-source" : "unverified-source"}>
          {evidence.quote_verified ? "Quote verified against source" : "Quote verification unavailable"}
        </span>
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

function MemoryCard({ decision }) {
  const [expanded, setExpanded] = useState(false);
  const sourceHref = externalHref(decision.source_reference);
  const repositoryHref = externalHref(decision.source_repository);
  return (
    <article className={`decision-card ${decision.status}`}>
      <div className="card-header">
        <span className={`status status-${decision.status}`}>{statusLabels[decision.status] || decision.status}</span>
        <span className="memory-date">Saved {new Date(decision.created_at).toLocaleString()}</span>
      </div>
      <h3>{decision.proposal}</h3>
      <p className="memory-source"><strong>Source:</strong> {decision.source_title}{decision.source_reference && <> · {sourceHref ? <a href={sourceHref} target="_blank" rel="noreferrer">Open reference</a> : decision.source_reference}</>}{repositoryHref && <> · <a href={repositoryHref} target="_blank" rel="noreferrer">Repository</a></>}</p>
      {decision.reason && <p className="reason"><span>Summary</span>{decision.reason}</p>}
      <dl className="decision-detail">
        <div><dt>Outcome basis</dt><dd>{decision.outcome_basis.replaceAll("_", " ")}</dd></div>
        <div><dt>Original evidence</dt><dd>{decision.evidence.length + decision.outcome_evidence.length} excerpts</dd></div>
      </dl>
      <button className="evidence-toggle" type="button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
        {expanded ? "Hide stored evidence" : "Inspect stored evidence"}
      </button>
      {expanded && <section className="evidence-panel" aria-label="Stored original evidence">
        <p className="evidence-note">Evidence quotes and reason associations are stored with this decision.</p>
        {decision.outcome_evidence.length > 0 && <div className="memory-evidence-group"><h4>Outcome evidence</h4><ul>{decision.outcome_evidence.map((item, index) => <Evidence evidence={item} key={`outcome-${index}`} />)}</ul></div>}
        {decision.evidence.length > 0 && <div className="memory-evidence-group"><h4>Discussion evidence</h4><ul>{decision.evidence.map((item, index) => <Evidence evidence={item} key={`evidence-${index}`} />)}</ul></div>}
        {decision.rejection_reasons.map((reason, index) => <div className="memory-evidence-group" key={`reason-${index}`}><h4>Rejection reason: {reason.text}</h4>{reason.evidence.length ? <ul>{reason.evidence.map((item, evidenceIndex) => <Evidence evidence={item} key={`${item.segment_id}-${evidenceIndex}`} />)}</ul> : <p>No source excerpt was stored for this reason.</p>}</div>)}
        {!decision.evidence.length && !decision.outcome_evidence.length && !decision.rejection_reasons.length && <p>No original evidence was stored.</p>}
      </section>}
    </article>
  );
}

function HistoricalCard({ decision }) {
  const [expanded, setExpanded] = useState(false);
  const sourceHref = externalHref(decision.source_reference);
  const repositoryHref = externalHref(decision.source_repository);
  const hasEvidence = decision.evidence.length || decision.outcome_evidence.length ||
    decision.rejection_reasons.some((reason) => reason.evidence.length);
  return (
    <article className={`decision-card historical-card ${decision.potential_conflict ? "potential-conflict" : ""}`}>
      <div className="card-header">
        <span className={`status status-${decision.status}`}>{statusLabels[decision.status] || decision.status}</span>
        {decision.potential_conflict && <span className="potential-conflict-label">Potential conflict · review both sources</span>}
      </div>
      <h3>{decision.proposal}</h3>
      <p className="memory-source"><strong>Historical source:</strong> {decision.source_title}{decision.source_reference && <> · {sourceHref ? <a href={sourceHref} target="_blank" rel="noreferrer">Open reference</a> : decision.source_reference}</>}{repositoryHref && <> · <a href={repositoryHref} target="_blank" rel="noreferrer">Repository</a></>}</p>
      {decision.reason && <p className="reason"><span>Stored summary</span>{decision.reason}</p>}
      {decision.rejection_reasons.length > 0 && <div className="historical-reasons"><strong>Recorded reasons</strong><ul>{decision.rejection_reasons.map((reason, index) => <li key={index}>{reason.text}</li>)}</ul></div>}
      <p className="historical-match">Jaccard keyword overlap: {Math.round(decision.relevance_score * 100)}% · matched: {decision.matched_proposals.join(", ")}</p>
      {decision.potential_conflict && <p className="conflict-explanation">Possible difference: {decision.conflict_reasons.join("; ")}. This lexical match is not a confirmed contradiction or a policy violation.</p>}
      <button className="evidence-toggle" type="button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
        {expanded ? "Hide historical evidence" : "Inspect historical evidence"}
      </button>
      {expanded && <section className="evidence-panel" aria-label="Historical source evidence">
        <p className="evidence-note">Historical reasoning is shown with the original source quotes. Quote verification confirms source presence, not logical support.</p>
        {decision.outcome_evidence.length > 0 && <div className="memory-evidence-group"><h4>Outcome evidence</h4><ul>{decision.outcome_evidence.map((item, index) => <Evidence evidence={item} key={`outcome-${index}`} />)}</ul></div>}
        {decision.evidence.length > 0 && <div className="memory-evidence-group"><h4>Discussion evidence</h4><ul>{decision.evidence.map((item, index) => <Evidence evidence={item} key={`discussion-${index}`} />)}</ul></div>}
        {decision.rejection_reasons.map((reason, index) => <div className="memory-evidence-group" key={`reason-${index}`}><h4>Reason: {reason.text}</h4>{reason.evidence.length ? <ul>{reason.evidence.map((item, evidenceIndex) => <Evidence evidence={item} key={`${item.segment_id}-${evidenceIndex}`} />)}</ul> : <p>No supporting source excerpt was stored for this reason.</p>}</div>)}
        {!hasEvidence && <p>No historical evidence excerpts were stored.</p>}
      </section>}
    </article>
  );
}

function App() {
  const [title, setTitle] = useState("Untitled discussion");
  const [sourceReference, setSourceReference] = useState("");
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [fileName, setFileName] = useState("");
  const [page, setPage] = useState("analysis");
  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryResults, setMemoryResults] = useState(null);
  const [memoryError, setMemoryError] = useState("");
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [githubUrl, setGithubUrl] = useState("");
  const [githubRepository, setGithubRepository] = useState(null);
  const [githubDiscussions, setGithubDiscussions] = useState(null);
  const [githubSelected, setGithubSelected] = useState(null);
  const [githubDetail, setGithubDetail] = useState(null);
  const [githubAnalysis, setGithubAnalysis] = useState(null);
  const [githubError, setGithubError] = useState("");
  const [githubLoading, setGithubLoading] = useState(false);
  const [githubDiscussionLoading, setGithubDiscussionLoading] = useState(false);
  const [githubAnalyzing, setGithubAnalyzing] = useState(false);

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
        body: JSON.stringify({ title: title.trim() || "Untitled discussion", source_reference: sourceReference.trim() || null, text: trimmed }),
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

  async function loadMemory(event) {
    event?.preventDefault();
    setMemoryLoading(true);
    setMemoryError("");
    try {
      const query = memoryQuery.trim();
      const endpoint = query
        ? `${API_BASE_URL}/api/memory/search?q=${encodeURIComponent(query)}`
        : `${API_BASE_URL}/api/memory`;
      const response = await fetch(endpoint);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw payload;
      setMemoryResults(payload);
    } catch (requestError) {
      setMemoryError(extractError(requestError));
    } finally {
      setMemoryLoading(false);
    }
  }

  function openMemory() {
    setPage("memory");
    loadMemory();
  }

  async function connectGitHub(event) {
    event.preventDefault();
    const canonicalUrl = canonicalGitHubRepositoryUrl(githubUrl);
    if (!canonicalUrl) {
      setGithubError("Enter a public repository URL in the form https://github.com/owner/repository.");
      return;
    }
    setGithubLoading(true);
    setGithubError("");
    setGithubRepository(null);
    setGithubDiscussions(null);
    setGithubSelected(null);
    setGithubDetail(null);
    setGithubAnalysis(null);
    setGithubUrl(canonicalUrl);
    try {
      const response = await fetch(`${API_BASE_URL}/api/github/discussions?repository_url=${encodeURIComponent(canonicalUrl)}`);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw { ...payload, status: response.status, retryAfter: response.headers.get("Retry-After") };
      setGithubRepository(payload.repository);
      setGithubDiscussions(payload);
    } catch (requestError) {
      setGithubError(githubErrorMessage(requestError));
    } finally {
      setGithubLoading(false);
    }
  }

  async function selectGitHubDiscussion(discussion) {
    setGithubSelected(discussion);
    setGithubDetail(null);
    setGithubAnalysis(null);
    setGithubDiscussionLoading(true);
    setGithubError("");
    try {
      const endpoint = `${API_BASE_URL}/api/github/discussions/${discussion.kind}/${discussion.number}?repository_url=${encodeURIComponent(githubUrl)}`;
      const response = await fetch(endpoint);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw { ...payload, status: response.status, retryAfter: response.headers.get("Retry-After") };
      setGithubDetail(payload);
    } catch (requestError) {
      setGithubError(githubErrorMessage(requestError));
    } finally {
      setGithubDiscussionLoading(false);
    }
  }

  async function analyzeGitHubDiscussion() {
    if (!githubSelected) return;
    setGithubAnalyzing(true);
    setGithubError("");
    try {
      const response = await fetch(`${API_BASE_URL}/api/github/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repository_url: githubUrl,
          kind: githubSelected.kind,
          number: githubSelected.number,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw { ...payload, status: response.status, retryAfter: response.headers.get("Retry-After") };
      setGithubAnalysis(payload);
    } catch (requestError) {
      setGithubError(githubErrorMessage(requestError));
    } finally {
      setGithubAnalyzing(false);
    }
  }

  return (
    <main>
      <header className="site-header">
        <a className="brand" href="#workspace"><span className="brand-mark">D</span><span>Decora</span></a>
        <nav className="site-nav" aria-label="Main navigation">
          <button className={page === "analysis" ? "nav-active" : "nav-button"} type="button" onClick={() => setPage("analysis")}>Analyze</button>
          <button className={page === "github" ? "nav-active" : "nav-button"} type="button" onClick={() => setPage("github")}>GitHub Import</button>
          <button className={page === "memory" ? "nav-active" : "nav-button"} type="button" onClick={openMemory}>Decision Memory</button>
        </nav>
        <span className="model-badge">Local Qwen3 inference</span>
      </header>
      {page === "analysis" && <>
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
          <label className="source-reference-label">Source reference (optional)<input value={sourceReference} onChange={(event) => setSourceReference(event.target.value)} maxLength="2000" placeholder="Discussion URL or source identifier" /></label>
          <label className="discussion-label">Raw discussion<textarea value={text} onChange={(event) => setText(event.target.value)} placeholder={"Alice: I propose using PostgreSQL for the service.\n\nBob: We need relational constraints for these entities."} rows="11" /></label>
          <div className="form-footer"><span>Messages are processed in chronological order. Uploaded files stay in your browser.</span><button type="submit" disabled={loading}>{loading ? "Analyzing with Qwen3…" : "Analyze discussion"}</button></div>
        </form>
        {error && <p className="error" role="alert">{error}</p>}
      </section>
      {result && <section className="results" aria-live="polite">
        <div className="results-heading"><div><p className="eyebrow">Extraction result</p><h2>{result.discussion_title}</h2><p>{result.total_messages} source messages · {result.model}</p></div><span className="verification-summary">{result.verified_decisions}/{result.decisions.length} decisions verified</span></div>
        <div className="summary-grid">{counts.map(({ status, count }) => <div className={`summary ${status}`} key={status}><strong>{count}</strong><span>{statusLabels[status]}</span></div>)}</div>
        {result.memory_conflicts?.length > 0 && <p className="memory-warning" role="status">Existing memory was kept because this analysis conflicted for: {result.memory_conflicts.join(", ")}. Review Decision Memory before retrying.</p>}
        {result.decisions.length ? <div className="decision-grid">{result.decisions.map((decision) => <DecisionCard decision={decision} key={decision.decision_id} />)}</div> : <div className="empty-result"><h3>No decisions recovered</h3><p>The model completed analysis but did not find a supported engineering decision in this discussion.</p></div>}
        <section className="historical-section" aria-live="polite">
          <div className="historical-heading"><div><p className="eyebrow">Prior records</p><h2>Historical Decisions</h2></div><p>Deterministic keyword matching · not semantic search</p></div>
          {result.historical_decisions?.length ? <div className="decision-grid">{result.historical_decisions.map((decision) => <HistoricalCard decision={decision} key={decision.id} />)}</div> : <div className="empty-result historical-empty"><h3>No related historical decisions found</h3><p>There are no saved decisions with matching normalized proposal keywords from another source.</p></div>}
        </section>
      </section>}
      </>}
      {page === "memory" && <section className="memory-page">
        <div className="memory-heading"><p className="eyebrow">Persistent local storage</p><h1>Decision Memory</h1><p className="intro">Search decisions saved after analysis, with their original source evidence and references.</p></div>
        <form className="memory-search" onSubmit={loadMemory}>
          <label htmlFor="memory-query">Search proposals, summaries, and rejection reasons</label>
          <div><input id="memory-query" value={memoryQuery} onChange={(event) => setMemoryQuery(event.target.value)} maxLength="200" placeholder="Try PostgreSQL or replication" /><button type="submit" disabled={memoryLoading}>{memoryLoading ? "Searching…" : "Search memory"}</button></div>
        </form>
        {memoryError && <p className="error" role="alert">{memoryError}</p>}
        {memoryResults && (memoryResults.length ? <div className="decision-grid memory-results">{memoryResults.map((decision) => <MemoryCard decision={decision} key={decision.id} />)}</div> : <div className="empty-result"><h3>No saved decisions found</h3><p>Analyze a discussion or change the search term.</p></div>)}
      </section>}
      {page === "github" && <section className="github-page">
        <div className="github-heading"><p className="eyebrow">Read-only public import</p><h1>Import from GitHub</h1><p className="intro">Load public issues and pull requests, inspect their discussion, then analyze a selected thread with local Qwen3.</p></div>
        <form className="github-connect" onSubmit={connectGitHub}>
          <label htmlFor="github-repository-url">Public GitHub repository URL</label>
          <div><input id="github-repository-url" value={githubUrl} onChange={(event) => setGithubUrl(event.target.value)} maxLength="500" placeholder="https://github.com/owner/repository" /><button type="submit" disabled={githubLoading}>{githubLoading ? "Loading repository…" : "Load repository"}</button></div>
          <p>Public read-only access only. Decora never comments on or changes repositories.</p>
        </form>
        {githubError && <p className="error github-error" role="alert">{githubError}</p>}
        {githubRepository && <section className="github-repository">
          <div><p className="eyebrow">Repository</p><h2>{githubRepository.full_name}</h2>{githubRepository.description && <p>{githubRepository.description}</p>}</div>
          <div className="github-repository-meta"><span>Default branch: {githubRepository.default_branch || "not provided"}</span><span>{githubRepository.stargazers_count} stars</span><span>{githubRepository.open_issues_count} open issues and pull requests</span><a href={githubRepository.html_url} target="_blank" rel="noreferrer">Open on GitHub</a></div>
        </section>}
        {githubDiscussions && <div className="github-discussion-columns">
          {[{ key: "issues", label: "Issues", items: githubDiscussions.issues }, { key: "pull_requests", label: "Pull requests", items: githubDiscussions.pull_requests }].map((group) => <section className="github-list" key={group.key}>
            <div className="github-list-heading"><h2>{group.label}</h2><span>{group.items.length}</span></div>
            {group.items.length ? <ul>{group.items.map((item) => <li key={`${item.kind}-${item.number}`}>
              <button className={`github-discussion-option ${githubSelected?.kind === item.kind && githubSelected?.number === item.number ? "selected" : ""}`} type="button" onClick={() => selectGitHubDiscussion(item)}>
                <span className="github-kind">{item.kind === "pull_request" ? "PR" : "Issue"} #{item.number} · {item.state || "unknown"}{item.draft ? " · draft" : ""}</span><strong>{item.title}</strong><span>by {item.author || "author unavailable"} · {item.comments_count} comments</span>
              </button>
            </li>)}</ul> : <div className="github-list-empty">No public {group.label.toLowerCase()} found within the import limit.</div>}
          </section>)}
        </div>}
        {githubDiscussionLoading && <p className="github-loading" role="status">Loading selected discussion and comments…</p>}
        {githubDetail && <section className="github-selected-detail">
          <div className="github-detail-title"><div><p className="eyebrow">Selected {githubDetail.discussion.kind === "pull_request" ? "pull request" : "issue"} #{githubDetail.discussion.number}</p><h2>{githubDetail.discussion.title}</h2></div><a href={githubDetail.discussion.html_url} target="_blank" rel="noreferrer">Open original discussion</a></div>
          <p>{githubDetail.discussion.body || "No opening description was provided."}</p>
          <p className="evidence-note">{githubDetail.comments.length} comments and reviews retrieved. Message bodies will be sent as untrusted discussion content.</p>
          {githubDetail.comments.length > 0 && <ul className="github-comment-preview">{githubDetail.comments.slice(0, 20).map((comment) => <li key={`${comment.kind}-${comment.id}`}><div><strong>{comment.author || "Author unavailable"}</strong><span>{comment.kind.replaceAll("_", " ")}{comment.created_at ? ` · ${comment.created_at}` : ""}</span>{comment.html_url && <a href={comment.html_url} target="_blank" rel="noreferrer">Original comment</a>}</div><p>{comment.body || "No comment text was provided."}</p></li>)}</ul>}
          <button type="button" onClick={analyzeGitHubDiscussion} disabled={githubAnalyzing}>{githubAnalyzing ? "Analyzing with local Qwen3…" : "Analyze selected discussion"}</button>
        </section>}
        {!githubDiscussions && !githubLoading && <div className="empty-result github-empty"><h3>Load a public repository to begin</h3><p>Decora imports a bounded page of public issues and pull requests. No token is required.</p></div>}
        {githubAnalysis && <section className="results github-results" aria-live="polite">
          <div className="results-heading"><div><p className="eyebrow">GitHub extraction result · {githubAnalysis.imported_messages} messages</p><h2>{githubAnalysis.discussion_title}</h2><p>{githubAnalysis.model} · <a href={githubAnalysis.discussion.html_url} target="_blank" rel="noreferrer">original GitHub discussion</a></p></div><span className="verification-summary">{githubAnalysis.verified_decisions}/{githubAnalysis.decisions.length} decisions verified</span></div>
          {githubAnalysis.memory_conflicts?.length > 0 && <p className="memory-warning" role="status">Existing memory was preserved because this import conflicted for: {githubAnalysis.memory_conflicts.join(", ")}.</p>}
          {githubAnalysis.decisions.length ? <div className="decision-grid">{githubAnalysis.decisions.map((decision) => <DecisionCard decision={decision} key={decision.decision_id} />)}</div> : <div className="empty-result"><h3>No decisions recovered</h3><p>The imported discussion did not establish a supported decision.</p></div>}
          <section className="historical-section"><div className="historical-heading"><div><p className="eyebrow">Prior records</p><h2>Historical Decisions</h2></div><p>Keyword matching · not semantic search</p></div>{githubAnalysis.historical_decisions?.length ? <div className="decision-grid">{githubAnalysis.historical_decisions.map((decision) => <HistoricalCard decision={decision} key={decision.id} />)}</div> : <div className="empty-result"><h3>No related historical decisions found</h3></div>}</section>
        </section>}
      </section>}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<React.StrictMode><App /></React.StrictMode>);
