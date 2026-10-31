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
- Connect decisions to relevant source-code changes.
- Preserve original discussion references as evidence.
- Surface historical decisions when related code is modified.

## Run locally

Start the API:

```bash
cd backend
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the React client in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite, paste a chronological discussion, or import a `.txt` transcript. The client sends text to the local FastAPI service at `http://127.0.0.1:8000` by default. Set `VITE_API_BASE_URL` to use a different API address.

The included `examples/synthetic_database_discussion.txt` is synthetic; it is not a PEP evaluation.

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

The Phase 2 implementation was assisted by OpenAI Codex using GPT-5. GPT-5 was used as a coding assistant during development only and is not used for Decora product inference.

## Project Status

Under development for Hacktoberfest Hack Day Sonipat 2026.

## License

MIT License.
