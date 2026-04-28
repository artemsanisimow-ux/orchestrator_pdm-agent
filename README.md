# 🎯 PM Agent Orchestrator

Connects all 12 PM agents into automated workflows. No LLM calls — pure coordination logic. Agents stay isolated; orchestrator reads their outputs and passes data as inputs to the next agent in the chain.

## Four workflows

| Workflow | Agents | Steps |
|----------|--------|-------|
| `sprint_cycle` | Discovery → PRD → Grooming → Planning → Stakeholder | 5 |
| `research_cycle` | CR → Metrics → Interview → Discovery → A/B → Roadmap | 6 |
| `retro_cycle` | Retro → CR → Metrics → Planning → Stakeholder | 5 |
| `full_cycle` | CR → Metrics → Interview → Discovery → PRD → Grooming → Planning → Retro → Stakeholder → Roadmap | 10 |

## Data flow between agents

```
CR signals.db      → top opportunities    → Discovery, Interview, Roadmap
Metrics anomalies  → CR signals           → full chain (closes the loop)
Retro action items → CR signals           → next cycle context
Discovery report   → report path          → PRD
AB report          → verdict + risk note  → Planning (pre-mortem)
Retro insights     → velocity factor      → Planning
Planning report    → sprint context       → Stakeholder
Interview quotes   → OST signals          → CR, Roadmap
Roadmap JSON       → now/next/later       → downstream context
```

Metrics agent closes the feedback loop: anomaly detected → CR signal created → flows into Discovery → Interview → Roadmap automatically.

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
INTERVIEW_DIR=../interview-agent
ROADMAP_DIR=../roadmap-agent
METRICS_DIR=../metrics-agent
```

```bash
python3 orchestrator.py --lang en
```

## Usage

```bash
# Interactive menu
python3 orchestrator.py --lang en

# Specify workflow
python3 orchestrator.py --lang en --workflow sprint_cycle

# Auto mode — no confirmation prompts
python3 orchestrator.py --lang en --workflow research_cycle --auto

# Show latest output from each agent
python3 orchestrator.py --status
```

## Status output

`--status` shows the latest output file from each of the 12 agents:

```
✅ CR              cr_digest_20260424.md              2026-04-24 11:30
✅ Discovery       discovery_report_20260424.md       2026-04-24 11:45
✅ Metrics         metrics_report_20260424.md         2026-04-24 12:00
✅ Interview       interview_report_20260424.md       2026-04-24 12:15
✅ Roadmap         roadmap_20260424.md                2026-04-24 12:30
⬜ PRD             no output yet
...
```

## Running tests

```bash
pytest test_orchestrator.py -v   # 59 tests
```

## The full system

| Agent | Repo | Description |
|-------|------|-------------|
| Discovery | [discovery-agent](https://github.com/artemsanisimow-ux/discovery-agent) | Raw data → insights → hypotheses |
| Grooming | [grooming-agent](https://github.com/artemsanisimow-ux/grooming-agent) | Jira + Linear → estimates → acceptance criteria |
| Planning | [planning-agent](https://github.com/artemsanisimow-ux/planning-agent) | Monte Carlo → sprint plan → publish |
| Retrospective | [retro-agent](https://github.com/artemsanisimow-ux/retro-agent) | Sprint analysis → action items → velocity insights |
| PRD | [prd-agent](https://github.com/artemsanisimow-ux/prd-agent) | Feature → full PRD → tasks in Jira + Linear |
| Stakeholder | [stakeholder-agent](https://github.com/artemsanisimow-ux/stakeholder-agent) | Sprint data → tailored comms for 5 audiences |
| A/B Testing | [ab-agent](https://github.com/artemsanisimow-ux/ab-agent) | Hypothesis → experiment design → ship/iterate/kill |
| Continuous Research | [cr-agent](https://github.com/artemsanisimow-ux/cr-agent) | Signals → OST → weekly digest → alerts |
| Metrics Monitor | [metrics-agent](https://github.com/artemsanisimow-ux/metrics-agent) | Anomaly detection → CR signals → Jira tasks |
| User Interview | [interview-agent](https://github.com/artemsanisimow-ux/interview-agent) | Transcripts → quotes → OST → next guide |
| Roadmap | [roadmap-agent](https://github.com/artemsanisimow-ux/roadmap-agent) | All signals → themed roadmap → NOW/NEXT/LATER |
| Orchestrator | this repo | Connects all 12 agents into 4 workflows |
