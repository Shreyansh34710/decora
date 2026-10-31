# Hackathon Submission

## Team Information

- **Team Name:** AstraNova
- **Team Members:**
  - Shreyansh Mishra
  - Irfan Rahaman

## Project Name

**Decora**

## Tagline

*Recover the decisions behind the code.*

## Selected Problem Statement

**Problem 6: Open Source Decision Intelligence and Knowledge Recovery**

## What We Are Building

Open-source projects have years of discussions spread across issues, pull requests, code reviews, and forums. Important technical decisions often happen in these conversations, but the reasons behind them are not always recorded in the project's documentation.

Decora aims to make this knowledge easier to find and understand.

It will analyse project discussions, identify the decisions made during them, and preserve the reasoning behind both accepted and rejected approaches. It will also connect those decisions to the relevant parts of the codebase so developers can understand the history behind existing implementations.

## Key Capabilities

- **Decision extraction:** Identify technical decisions from issues, pull requests, reviews, and discussions.
- **Reasoning recovery:** Understand why a particular approach was accepted or rejected.
- **Alternative analysis:** Preserve proposed alternatives and the reasons they were not selected.
- **Code connection:** Link recovered decisions to the relevant files and code changes.
- **Evidence tracking:** Keep references to the original discussions so developers can verify the results.
- **Historical context for new PRs:** Surface relevant past decisions when a new pull request touches related code.

## AI Models and Their Role

**Product inference model:** Qwen3:8b, run locally through Ollama.

Qwen3:8b is responsible for understanding technical discussions, extracting decisions, distinguishing accepted and rejected proposals, and recovering the reasoning behind them. Decora uses this local open-weight model for product inference.

**Reason for selection:** A local open-weight model keeps the main intelligence tasks independent of proprietary inference APIs and aligned with the hackathon's open-source AI requirements.

## AI-Assisted Development Disclosure

The Phase 2 implementation was assisted by OpenAI Codex using GPT-5. This coding assistant was used during development only. GPT-5 is not used for Decora product inference.

## OpenAI API Usage

Decora does not use the OpenAI API for product inference. Product inference runs locally through Ollama using Qwen3:8b.

## Our Focus

The main challenge is not simply summarising long discussions. Decora needs to identify what was actually decided, which alternatives were rejected, why they were rejected, and where the supporting evidence can be found.

We will focus on making these recovered decisions useful and verifiable for developers working on the project.
