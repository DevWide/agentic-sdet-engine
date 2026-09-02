# 🤖 Agentic SDET Engine

> Autonomous Software Quality & Self-Healing Testing Engine powered by **LangGraph**, **LangChain**, and **OpenTelemetry**.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![OpenTelemetry](https://img.shields.io/badge/Observability-OpenTelemetry-blueviolet.svg)](https://opentelemetry.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📌 Overview

The **Agentic SDET Engine** is an enterprise-grade multi-agent software quality engineering platform designed to address the high maintenance overhead of automated test suites caused by contract updates, selector drift, and flaky assertions.

Leveraging stateful, cyclic orchestration via **LangGraph**, the engine:
1. Ingests natural-language acceptance criteria and feature specifications.
2. Synthesizes isolated, production-ready unit and integration tests in **Pytest** using structured schema enforcement (**Pydantic**).
3. Executes test suites inside an isolated runtime sandbox via subprocess execution.
4. Dynamically triggers an autonomous **Self-Healing Loop** upon detecting assertion failures or runtime errors, iteratively refining code until all criteria pass.
5. Emits end-to-end distributed tracing via native **OpenTelemetry (OTel)** instrumentation conforming to Cloud Native Computing Foundation (CNCF) standards.

---

## 🏗️ State Graph Architecture

```text
               ┌───────────────────────┐
               │ 1. Test Synthesizer   │ (LangChain + Pydantic Structured Output)
               └───────────┬───────────┘
                           │
                           ▼
               ┌───────────────────────┐
               │ 2. Sandbox Executor   │ (Isolated Subprocess Execution via Pytest)
               └───────────┬───────────┘
                           │
               ┌───────────┴───────────┐
        [Pass]                         [Fail]
           │                               │
           ▼                               ▼
┌─────────────────────┐       ┌─────────────────────────┐
│ State: Completed    │       │ 3. Self-Healing Agent   │ (Traceback & Context Repair)
└─────────────────────┘       └────────────┬────────────┘
                                           │
                                    (Cyclic Repair Loop)
                                           │
                                           └───► [Re-execute in Sandbox]