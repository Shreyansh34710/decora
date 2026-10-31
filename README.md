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

## Technology Stack

- Backend: Python and FastAPI
- Frontend: React and Vite
- AI: Open-weight language model
- Testing: Pytest
- CI: GitHub Actions

## AI Model

Qwen3-8B is the initial candidate for decision extraction and reasoning recovery. It will be evaluated against representative discussions before final integration.

No closed-model APIs are planned for application inference.

## Project Status

Under development for Hacktoberfest Hack Day Sonipat 2026.

## License

MIT License.