# Decora

**Recover the decisions behind the code.**

Decora is an open-source decision intelligence and knowledge recovery system. It analyzes public technical discussions, GitHub issues, pull requests, comments, and development threads to recover the decisions that shaped software projects.

## Problem

Important technical decisions are buried in lengthy discussions. Developers often struggle to discover why an approach was selected, which alternatives were rejected, and what historical context should inform a new change.

## Proposed Solution

Decora aims to:

- Extract technical decisions from discussions.
- Identify accepted and rejected approaches.
- Recover the reasoning behind decisions.
- Preserve original discussion references as evidence.
- Retrieve related historical decisions through deterministic normalized keyword matching.

Connecting decisions to source-code changes or automatically surfacing them when code is modified are future possibilities. Decora does not currently monitor repositories for code changes. Historical retrieval is lexical; it is not semantic or vector search.

## Run locally

### Prerequisites and installation

Install Python 3, Node.js with npm, and [Ollama](https://ollama.com/download) using the installation instructions for your operating system. From the repository root, create and activate a virtual environment, then install the backend requirements:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead. Install the frontend packages:

```bash
cd frontend
npm install
```

Download the local product inference model:

```bash
ollama pull qwen3:8b
```

### Configuration

The frontend reads `VITE_API_BASE_URL` at build/dev-server startup. It defaults to `http://127.0.0.1:8000`. To use another backend address, create `frontend/.env.local` with a value such as:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

The backend reads `DECORA_DB_PATH` to choose its SQLite database file. It defaults to `backend/data/decora.db`; relative paths are resolved from the backend process's working directory. For example, set a path relative to the `backend` directory before starting the API:

```bash
export DECORA_DB_PATH=./data/demo-memory.db
```

These examples contain no credentials. Restart the relevant process after changing configuration.

### Start the services

Ensure Ollama is running. If it is not already running as a background service or desktop app, start it in a terminal:

```bash
ollama serve
```

In another terminal, verify the model is available:

```bash
ollama list
```

The list should include `qwen3:8b`. Start the FastAPI backend from the repository root (activate `.venv` in this terminal first if needed):

```bash
cd backend
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On Windows, use `.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000` from `backend`.

In a third terminal, start the Vite frontend:

```bash
cd frontend
npm run dev
```

Open the local URL printed by Vite. Decora uses local Qwen3:8b through Ollama for product inference.

## Demo walkthrough

1. Start Ollama, the FastAPI backend, and the Vite frontend using the steps above.
2. Open **GitHub Import**, enter a public repository URL such as `https://github.com/owner/repository`, and load it.
3. Select an issue or pull request to view its original discussion and comments.
4. Choose **Analyze selected discussion**. Review the extracted decisions, outcome labels, quoted evidence, and source links.
5. Open **Decision Memory** to search saved decisions and inspect their source evidence.
6. To demonstrate historical retrieval, analyze another discussion from a different source with a related proposal. Decora may show matching prior records and potential conflicts based on keyword overlap; this is a heuristic and not a confirmed contradiction.

GitHub uses unauthenticated public API rate limits. If an import is rate-limited, wait for the displayed retry guidance or use the existing **Analyze** page to paste the discussion text or upload a `.txt` transcript. This fallback uses the same extraction and local inference pipeline.

The included `examples/synthetic_database_discussion.txt` is synthetic; it is not a PEP evaluation.

## Decision Memory

Successful analyses are saved in a local SQLite database at `backend/data/decora.db` by default. The database is created automatically when the API first saves or reads memory. It stores decision outcomes, summaries, separately associated rejection reasons and evidence, source titles/references, and timestamps available in evidence.

Set `DECORA_DB_PATH` to configure a different database file. Absolute paths are recommended; relative paths are resolved from the backend process's current working directory. For example:

```bash
DECORA_DB_PATH=/path/to/decora-memory.db ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use the **Decision Memory** section in the client to list and search saved decisions. The API also exposes `GET /api/memory` and `GET /api/memory/search?q=...`; both return stored evidence and source metadata.

After analysis, Decora also returns related historical decisions and exposes `POST /api/memory/related`. Retrieval lowercases proposal text, splits it into alphanumeric keywords, removes a fixed list of generic words, and ranks exact-token overlap with Jaccard similarity; matches below `0.25` are excluded. The current source is excluded. A potential conflict is labeled when decisive stored outcomes differ or proposal wording contains opposite action terms. This is a transparent lexical heuristic, not semantic/vector search or a confirmed contradiction. Historical source reasoning and evidence remain available for review.

To inspect the default database with the SQLite command-line tool:

```bash
sqlite3 backend/data/decora.db 'SELECT id, proposal, status, source_title FROM decisions ORDER BY created_at DESC;'
```

To reset local memory, stop the API and remove the configured database file. For the default location:

```bash
rm -f backend/data/decora.db backend/data/decora.db-wal backend/data/decora.db-shm
```

The database is local application data and is ignored by Git. When a source reference is provided, it identifies the source for idempotency; otherwise the title and exact discussion text identify it. Reanalyzing the same source and proposal returns the same stored ID without adding a duplicate. If a later analysis produces conflicting status or evidence for that source and proposal, Decora keeps the existing record and reports the conflict in the extraction response.

## Public GitHub import

The **GitHub Import** section accepts only public repository URLs in the form `https://github.com/{owner}/{repository}`. Decora uses unauthenticated, read-only requests to the fixed `https://api.github.com` origin. No token is required. It loads repository details, issues, pull requests, issue discussion comments, PR discussion comments, review comments, and review bodies. Imported messages retain their GitHub author, timestamp, stable comment ID, and original GitHub URL before using the existing local Qwen3:8b through Ollama extraction pipeline.

Imports are bounded: at most 100 issues and 100 pull requests are listed; each comment category is capped at 100 items over at most two pages; API responses are capped at 2 MiB each; and an individual discussion is limited to 512 KiB of text. The unauthenticated public API has GitHub-enforced rate limits, so importing can return a retryable rate-limit response. Decora reports that state and any available retry delay. Decision Memory retains both the selected discussion URL and the repository URL. Repository import is read-only: Decora never comments on, edits, or submits changes to GitHub.

Imported GitHub discussion content is untrusted data. Decora instructs the local model to treat it as source material and ignore embedded commands, but this prompt-injection resistance is a mitigation, not a guarantee; imported content may still influence model output and extracted decisions should be reviewed.

## Technology Stack

- Backend: Python and FastAPI
- Frontend: React and Vite
- AI: Open-weight language model
- Testing: Pytest
- CI: GitHub Actions

## AI Model

Decora uses Qwen3:8b locally through Ollama for decision extraction and reasoning recovery. This open-weight model performs product inference.

No closed-model API is used for product inference.

## AI-Assisted Development Disclosure

OpenAI Codex provided coding assistance during development, including GPT-5 and GPT-5.3-Codex. This assistance supported implementation and documentation; it is separate from product inference. Decora's product inference uses only local Qwen3:8b through Ollama.

## Project Status

Under development for Hacktoberfest Hack Day Sonipat 2026.

## License

MIT License.
