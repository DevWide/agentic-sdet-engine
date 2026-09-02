# 🤖 Agentic SDET Engine

> Autonomous Software Quality & Self-Healing Testing Engine powered by **LangGraph**, **LangChain**, and **OpenTelemetry**.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![OpenTelemetry](https://img.shields.io/badge/Observability-OpenTelemetry-blueviolet.svg)](https://opentelemetry.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📌 Visão Geral

O **Agentic SDET Engine** é um sistema multi-agente de Engenharia de Qualidade de Software projetado para resolver o alto custo de manutenção de testes automatizados causados por alterações de contratos e inconsistências de seletores (*flakiness*).

Utilizando uma máquina de estados cíclica com **LangGraph**, a engine:
1. Ingere requisitos ou user stories em linguagem natural.
2. Sintetiza testes unitários e de integração em **Pytest** com saídas estruturadas (**Pydantic**).
3. Executa a suíte gerada em um sandbox isolado via subprocesso.
4. Aciona automaticamente um loop de **autocura (*Self-Healing*)** caso ocorram falhas de asserção, refatorando o teste até a aprovação.
5. Emite rastreabilidade completa via **OpenTelemetry (OTel)** padronizada pela Cloud Native Computing Foundation (CNCF).

---

## 🏗️ Arquitetura do Grafo de Estados

```text
               ┌───────────────────────┐
               │ 1. Test Synthesizer   │ (LangChain + Pydantic)
               └───────────┬───────────┘
                           │
                           ▼
               ┌───────────────────────┐
               │ 2. Sandbox Executor   │ (Pytest isolado)
               └───────────┬───────────┘
                           │
               ┌───────────┴───────────┐
       [Sucesso]                       [Falha]
           │                               │
           ▼                               ▼
┌─────────────────────┐       ┌─────────────────────────┐
│ Status: Aprovado    │       │ 3. Self-Healing Agent   │
└─────────────────────┘       └────────────┬────────────┘
                                           │
                                     (Loop de correção)
                                           │
                                           └───► [Reexecuta no Executor]
