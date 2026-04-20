# 🎯 PM Agent Orchestrator

Connects all 8 PM agents into coherent workflows. No LLM calls — pure coordination logic. Agents stay isolated; orchestrator reads their outputs and passes data as inputs to the next agent in the chain.

## Four workflows

| Workflow | Agents | When to use |
|----------|--------|-------------|
| `sprint_cycle` | Discovery → PRD → Grooming → Planning → Stakeholder | Start of a new sprint |
| `research_cycle` | CR → Discovery → A/B Testing | Between sprints, validating hypotheses |
| `retro_cycle` | Retro → CR → Planning → Stakeholder | End of sprint, planning next one |
| `full_cycle` | CR → Discovery → PRD → Grooming → Planning → Retro → Stakeholder | Full product cycle |

## Data flow between agents

```
CR signals.db     → top opportunities  → Discovery (product context)
CR digest.md      → planning risks     → Planning (pre-mortem)
Discovery report  → report path        → PRD
Retro insights    → action items       → CR (as analytics signals)
Retro insights    → velocity factor    → Planning
A/B report        → risk note          → Planning
Planning report   → sprint context     → Stakeholder
```

Agents never call each other directly. The orchestrator reads output files and passes relevant data as input parameters to the next agent.

## Quick start

```bash
git clone https://github.com/artemsanisimow-ux/orchestrator.git
cd orchestrator
python3 -m venv venv
source venv/bin/activate
pip install langgraph langchain-anthropic langgraph-checkpoint-sqlite python-dotenv requests
```

Add to `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
LANGUAGE=en

# Agent directories (defaults to sibling folders)
DISCOVERY_DIR=../discovery-agent
GROOMING_DIR=../grooming-agent
PLANNING_DIR=../planning-agent
RETRO_DIR=../retro-agent
PRD_DIR=../prd-agent
STAKEHOLDER_DIR=../stakeholder-agent
AB_DIR=../ab-agent
CR_DIR=../cr-agent
```

```bash
python3 orchestrator.py --lang en
```

## Usage

```bash
# Interactive menu
python3 orchestrator.py --lang en

# Specify workflow directly
python3 orchestrator.py --lang en --workflow sprint_cycle

# Auto mode — no confirmation prompts
python3 orchestrator.py --lang en --workflow retro_cycle --auto

# Show latest output from each agent
python3 orchestrator.py --status

# Russian
python3 orchestrator.py --lang ru
```

## How it works

1. You choose a workflow (or pass `--workflow`)
2. For each agent: orchestrator reads relevant output files from previous agents, calls the agent's `run_*` function with extracted context
3. On error: shows what failed and asks whether to continue
4. Saves session log as JSON

No LLM is used for routing or handoff decisions — all coordination is pure Python logic. This makes the orchestrator fast, deterministic, and free.

## Running tests

```bash
pytest test_orchestrator.py -v   # 59 tests
```

Tests cover: OrchState, file utilities, data extractors, runners (mocked agents), workflow definitions, integration tests.

## The full system

| Agent | Repo |
|-------|------|
| Discovery | [discovery-agent](https://github.com/artemsanisimow-ux/discovery-agent) |
| Grooming | [grooming-agent](https://github.com/artemsanisimow-ux/grooming-agent) |
| Planning | [planning-agent](https://github.com/artemsanisimow-ux/planning-agent) |
| Retrospective | [retro-agent](https://github.com/artemsanisimow-ux/retro-agent) |
| PRD | [prd-agent](https://github.com/artemsanisimow-ux/prd-agent) |
| Stakeholder | [stakeholder-agent](https://github.com/artemsanisimow-ux/stakeholder-agent) |
| A/B Testing | [ab-agent](https://github.com/artemsanisimow-ux/ab-agent) |
| Continuous Research | [cr-agent](https://github.com/artemsanisimow-ux/cr-agent) |
| Orchestrator | this repo |
