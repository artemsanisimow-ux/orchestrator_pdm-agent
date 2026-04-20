"""
Orchestrator
============
Connects all 8 PM agents into coherent workflows.
No LLM calls — pure coordination logic (energy-efficient).

Agents stay isolated; orchestrator reads their outputs and
passes data as inputs to the next agent in the chain.

Workflows:
  sprint_cycle   — Discovery → PRD → Grooming → Planning → Stakeholder
  research_cycle — CR → Discovery → A/B Testing
  retro_cycle    — Retro → CR (action items as signals) → Planning → Stakeholder
  full_cycle     — CR → Discovery → PRD → Grooming → Planning → Retro → Stakeholder

Setup:
    All agents must be importable (same venv, PYTHONPATH, or sibling dirs).

Usage:
    python3 orchestrator.py --lang en
    python3 orchestrator.py --lang en --workflow sprint_cycle
    python3 orchestrator.py --lang ru --workflow research_cycle
    python3 orchestrator.py --status
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()
from i18n import get_language, set_language
from i18n import t as tr

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

AGENT_DIRS: dict[str, str] = {
    "discovery":   os.getenv("DISCOVERY_DIR",   "../discovery-agent"),
    "grooming":    os.getenv("GROOMING_DIR",    "../grooming-agent"),
    "planning":    os.getenv("PLANNING_DIR",    "../planning-agent"),
    "retro":       os.getenv("RETRO_DIR",       "../retro-agent"),
    "prd":         os.getenv("PRD_DIR",         "../prd-agent"),
    "stakeholder": os.getenv("STAKEHOLDER_DIR", "../stakeholder-agent"),
    "ab":          os.getenv("AB_DIR",          "../ab-agent"),
    "cr":          os.getenv("CR_DIR",          "../cr-agent"),
}

AGENT_MODULES: dict[str, str] = {
    "discovery":   "discovery_agent_v2",
    "grooming":    "grooming_agent",
    "planning":    "planning_agent_v2",
    "retro":       "retro_agent",
    "prd":         "prd_agent",
    "stakeholder": "stakeholder_agent",
    "ab":          "ab_agent",
    "cr":          "cr_agent",
}

WORKFLOWS = ["sprint_cycle", "research_cycle", "retro_cycle", "full_cycle"]


# ─────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────

class OrchState:
    """Lightweight mutable state — tracks outputs of each agent."""

    def __init__(self, workflow: str, session_id: str):
        self.workflow    = workflow
        self.session_id  = session_id
        self.started_at  = datetime.now().isoformat()
        self.completed:  list[str]       = []
        self.skipped:    list[str]       = []
        self.outputs:    dict[str, Any]  = {}
        self.errors:     dict[str, str]  = {}

    def record(self, agent: str, files: list[str], data: dict) -> None:
        self.completed.append(agent)
        self.outputs[agent] = {"files": files, "data": data}

    def fail(self, agent: str, error: str) -> None:
        self.errors[agent] = error

    def to_json(self) -> str:
        return json.dumps({
            "session_id":   self.session_id,
            "workflow":     self.workflow,
            "started_at":   self.started_at,
            "finished_at":  datetime.now().isoformat(),
            "completed":    self.completed,
            "skipped":      self.skipped,
            "errors":       self.errors,
            "output_files": {k: v["files"] for k, v in self.outputs.items()},
        }, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# AGENT LOADER
# ─────────────────────────────────────────────

_loaded: dict[str, Any] = {}


def load_agent(name: str) -> Any:
    """Dynamically import agent module from its directory."""
    if name in _loaded:
        return _loaded[name]

    agent_dir  = Path(AGENT_DIRS[name]).resolve()
    module_name = AGENT_MODULES[name]

    if not agent_dir.exists():
        raise FileNotFoundError(
            f"Agent directory not found: {agent_dir}\n"
            f"Set {name.upper()}_DIR in .env or place agents in sibling folders.\n"
            f"Example: DISCOVERY_DIR=../discovery-agent"
        )

    if str(agent_dir) not in sys.path:
        sys.path.insert(0, str(agent_dir))

    spec = importlib.util.spec_from_file_location(
        module_name, agent_dir / f"{module_name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _loaded[name] = mod
    return mod


# ─────────────────────────────────────────────
# FILE UTILITIES
# ─────────────────────────────────────────────

def find_latest(pattern: str, search_dirs: list[str] | None = None) -> Path | None:
    dirs = [Path(d) for d in (search_dirs or ["."])]
    matches = [f for d in dirs if d.exists() for f in d.glob(pattern)]
    return max(matches, key=lambda p: p.stat().st_mtime) if matches else None


def read_text(path: Path | None, max_chars: int = 4000) -> str:
    if path and path.exists():
        text = path.read_text(encoding="utf-8")
        return text[:max_chars]
    return ""


def read_json(path: Path | None) -> dict:
    if path and path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def agent_dirs(name: str) -> list[str]:
    return [AGENT_DIRS[name], "."]


# ─────────────────────────────────────────────
# DATA EXTRACTORS
# ─────────────────────────────────────────────

def extract_cr(state: OrchState) -> dict:
    opportunities, planning_risks = [], []

    cr_db = find_latest("cr_signals.db", agent_dirs("cr"))
    if cr_db:
        try:
            conn = sqlite3.connect(str(cr_db))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT title, signal_count, avg_sentiment FROM opportunities "
                "WHERE status='open' ORDER BY signal_count DESC LIMIT 5"
            ).fetchall()
            opportunities = [dict(r) for r in rows]
            conn.close()
        except Exception:
            pass

    digest_text = read_text(find_latest("cr_digest_*.md", agent_dirs("cr")), 3000)
    if digest_text:
        in_risks = False
        for line in digest_text.split("\n"):
            if "Planning Risk" in line or "Риски для планирования" in line:
                in_risks = True
                continue
            if in_risks:
                if line.startswith(("## ", "# ")):
                    break
                if line.startswith("- "):
                    planning_risks.append(line[2:].strip())

    return {
        "opportunities":      opportunities,
        "planning_risks":     planning_risks,
        "digest_text":        digest_text,
        "discovery_insights": "\n".join(
            f"- {o['title']} ({o['signal_count']} signals)" for o in opportunities
        ),
    }


def extract_discovery(state: OrchState) -> dict:
    f = find_latest("discovery_report*.md", agent_dirs("discovery"))
    return {"report_path": str(f) if f else "", "content": read_text(f)}


def extract_retro(state: OrchState) -> dict:
    insights_file = find_latest("retro_planning_insights_*.json", agent_dirs("retro"))
    insights = read_json(insights_file)
    report_text = read_text(find_latest("retro_report_*.md", agent_dirs("retro")), 3000)

    action_items = insights.get("action_items", [])
    if not action_items:
        for line in report_text.split("\n"):
            if line.startswith("- ") and len(line) > 5:
                action_items.append(line[2:].strip())

    return {
        "insights":        insights,
        "action_items":    action_items[:10],
        "velocity_factor": insights.get("velocity_adjustment", 1.0),
        "report_text":     report_text,
    }


def extract_ab(state: OrchState) -> dict:
    content = read_text(find_latest("ab_report_*.md", agent_dirs("ab")), 2000)
    verdict = velocity_note = risk_note = ""
    for line in content.split("\n"):
        low = line.lower()
        if "verdict:" in low or "вердикт:" in low:
            raw = line.split(":", 1)[-1].strip() if ":" in line else ""
            # strip markdown bold (**), emoji, whitespace
            raw = raw.replace("*", "").strip()
            verdict = raw.split()[0].lower() if raw else ""
        if "velocity:" in low:
            velocity_note = line.split(":", 1)[-1].strip()
        if "risk:" in low or "риски:" in low:
            risk_note = line.split(":", 1)[-1].strip()
    return {"verdict": verdict, "velocity_note": velocity_note, "risk_note": risk_note}


def extract_planning(state: OrchState) -> dict:
    return {"content": read_text(find_latest("sprint_plan_*.md", agent_dirs("planning")), 3000)}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def L(en: str, ru: str) -> str:
    return en if get_language() == "en" else ru


def header(text: str) -> None:
    print(f"\n{'═' * 60}\n  {text}\n{'═' * 60}")


def step_banner(n: int, total: int, agent: str, desc: str) -> None:
    print(f"\n{'─' * 60}\n  [{n}/{total}] {agent.upper()} — {desc}\n{'─' * 60}")


def ask(prompt_en: str, prompt_ru: str) -> str:
    return input(L(prompt_en, prompt_ru)).strip().lower()


def ask_continue(agent: str) -> bool:
    return ask(
        f"Run {agent} agent? (y/n/s=skip): ",
        f"Запустить агент {agent}? (y/n/s=пропустить): "
    ) not in ("n", "s", "no", "нет", "п")


def save_session(state: OrchState) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"orchestrator_session_{state.session_id}_{ts}.json"
    Path(fname).write_text(state.to_json(), encoding="utf-8")
    return fname


def _collect_files(pattern: str) -> list[str]:
    return [str(f) for f in sorted(Path(".").glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)[:3]]


# ─────────────────────────────────────────────
# RUNNERS — one per agent
# Each returns (output_files, metadata_dict)
# ─────────────────────────────────────────────

def run_cr(state: OrchState) -> tuple[list[str], dict]:
    mod = load_agent("cr")
    _, sid = mod.run_cr()
    return _collect_files("cr_digest_*.md"), {"session_id": sid}


def run_discovery(state: OrchState) -> tuple[list[str], dict]:
    cr = extract_cr(state)
    mod = load_agent("discovery")
    _, sid = mod.run_discovery(product_context=cr["discovery_insights"])
    return _collect_files("discovery_report*.md"), {"session_id": sid}


def run_prd(state: OrchState) -> tuple[list[str], dict]:
    disc = extract_discovery(state)
    mod = load_agent("prd")
    _, sid = mod.run_prd(discovery_report=disc["report_path"])
    return _collect_files("prd_*.md"), {"session_id": sid}


def run_grooming(state: OrchState) -> tuple[list[str], dict]:
    mod = load_agent("grooming")
    _, sid = mod.run_grooming()
    return _collect_files("grooming_report_*.md"), {"session_id": sid}


def run_planning(state: OrchState) -> tuple[list[str], dict]:
    retro = extract_retro(state)
    cr    = extract_cr(state)
    ab    = extract_ab(state)

    ctx_parts = []
    if retro["action_items"]:
        ctx_parts.append(L("Retro: ", "Ретро: ") + "; ".join(retro["action_items"][:3]))
    if cr["planning_risks"]:
        ctx_parts.append(L("Research risks: ", "Риски: ") + "; ".join(cr["planning_risks"][:2]))
    if ab["risk_note"]:
        ctx_parts.append(f"A/B ({ab['verdict']}): {ab['risk_note']}")

    if ctx_parts:
        os.environ["ORCH_PLANNING_CONTEXT"] = " | ".join(ctx_parts)

    mod = load_agent("planning")
    _, sid = mod.run_planning()
    os.environ.pop("ORCH_PLANNING_CONTEXT", None)
    return _collect_files("sprint_plan_*.md"), {"session_id": sid, "context": ctx_parts}


def run_retro(state: OrchState) -> tuple[list[str], dict]:
    mod = load_agent("retro")
    _, sid = mod.run_retro()
    return _collect_files("retro_report_*.md"), {"session_id": sid}


def run_stakeholder(state: OrchState) -> tuple[list[str], dict]:
    plan = extract_planning(state)
    mod = load_agent("stakeholder")
    _, sid = mod.run_stakeholder(context=plan["content"][:500])
    return _collect_files("stakeholder_*.md"), {"session_id": sid}


def run_ab(state: OrchState) -> tuple[list[str], dict]:
    disc = extract_discovery(state)
    cr   = extract_cr(state)
    mod  = load_agent("ab")
    _, sid = mod.run_ab_test(
        discovery_insights=(disc["content"] or cr["digest_text"])[:2000],
    )
    return _collect_files("ab_report_*.md"), {"session_id": sid}


def run_cr_with_retro(state: OrchState) -> tuple[list[str], dict]:
    """Feed retro action items into CR DB before running CR agent."""
    retro = extract_retro(state)
    items = retro["action_items"]

    if items:
        cr_db = next(
            (Path(d) / "cr_signals.db" for d in [AGENT_DIRS["cr"], "."]
             if (Path(d) / "cr_signals.db").exists()),
            Path("cr_signals.db")
        )
        try:
            conn = sqlite3.connect(str(cr_db))
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT,
                    raw_text TEXT, opportunity TEXT, sentiment REAL,
                    tags_json TEXT, created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS opportunities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT UNIQUE,
                    outcome TEXT DEFAULT '', signal_count INTEGER DEFAULT 1,
                    avg_sentiment REAL, status TEXT DEFAULT 'open',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
            """)
            for item in items:
                opp = f"Retro: {item[:50]}"
                conn.execute(
                    "INSERT INTO signals (source, raw_text, opportunity, sentiment, tags_json) "
                    "VALUES (?,?,?,?,?)",
                    ("analytics", item, opp, -0.3, '["retro","action_item"]')
                )
                conn.execute("""
                    INSERT INTO opportunities (title, signal_count, avg_sentiment)
                    VALUES (?,1,-0.3)
                    ON CONFLICT(title) DO UPDATE SET
                        signal_count=signal_count+1, updated_at=datetime('now')
                """, (opp,))
            conn.commit()
            conn.close()
            print(f"   ✅ {L(f'{len(items)} retro items → CR signals', f'{len(items)} action items из ретро → CR сигналы')}")
        except Exception as e:
            print(f"   ⚠️  CR pre-load: {e}")

    return run_cr(state)


# ─────────────────────────────────────────────
# WORKFLOW DEFINITIONS
# (key, desc_en, desc_ru, runner)
# ─────────────────────────────────────────────

Step = tuple[str, str, str, Callable]

WORKFLOW_STEPS: dict[str, list[Step]] = {
    "sprint_cycle": [
        ("discovery",   "Discover user needs",                    "Исследование потребностей",         run_discovery),
        ("prd",         "Generate PRD",                           "Генерация PRD",                     run_prd),
        ("grooming",    "Groom backlog",                          "Груминг беклога",                   run_grooming),
        ("planning",    "Plan sprint (Monte Carlo + pre-mortem)", "Планирование (Monte Carlo)",         run_planning),
        ("stakeholder", "Stakeholder communications",             "Коммуникации стейкхолдеров",        run_stakeholder),
    ],
    "research_cycle": [
        ("cr",        "Collect signals + update OST",             "Сбор сигналов + обновление OST",    run_cr),
        ("discovery", "Deep discovery with CR context",           "Discovery с контекстом CR",         run_discovery),
        ("ab",        "Design experiment",                        "Дизайн эксперимента",               run_ab),
    ],
    "retro_cycle": [
        ("retro",       "Analyze sprint",                         "Анализ спринта",                    run_retro),
        ("cr",          "Retro → OST signals",                    "Ретро → сигналы OST",               run_cr_with_retro),
        ("planning",    "Plan next sprint with retro insights",   "Планирование с инсайтами ретро",    run_planning),
        ("stakeholder", "Communicate results",                    "Коммуникация результатов",          run_stakeholder),
    ],
    "full_cycle": [
        ("cr",          "Collect signals",                        "Сбор сигналов",                     run_cr),
        ("discovery",   "Discovery with CR context",              "Discovery с CR контекстом",         run_discovery),
        ("prd",         "Generate PRD",                           "Генерация PRD",                     run_prd),
        ("grooming",    "Groom backlog",                          "Груминг беклога",                   run_grooming),
        ("planning",    "Plan sprint",                            "Планирование спринта",              run_planning),
        ("retro",       "Retrospective",                          "Ретроспектива",                     run_retro),
        ("stakeholder", "Stakeholder communications",             "Коммуникации стейкхолдеров",        run_stakeholder),
    ],
}


# ─────────────────────────────────────────────
# ORCHESTRATOR
# ─────────────────────────────────────────────

def run_workflow(workflow: str, session_id: str | None = None,
                 auto: bool = False) -> OrchState:
    sid   = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    state = OrchState(workflow, sid)
    steps = WORKFLOW_STEPS[workflow]

    header(L(
        f"PM Orchestrator | {workflow.replace('_', ' ').title()} | Session: {sid}",
        f"PM Оркестратор | {workflow.replace('_', ' ')} | Сессия: {sid}",
    ))

    print(f"\n{L('Workflow plan:', 'План воркфлоу:')}")
    for i, (key, en, ru, _) in enumerate(steps, 1):
        print(f"  {i}. {key.upper()} — {L(en, ru)}")

    if not auto:
        if ask("Start? (y/n): ", "Запустить? (y/n): ") not in ("y", "yes", "да"):
            print(L("Cancelled.", "Отменено."))
            return state

    for i, (key, en, ru, runner) in enumerate(steps, 1):
        step_banner(i, len(steps), key, L(en, ru))

        if not auto and not ask_continue(key):
            state.skipped.append(key)
            print(f"  ⏭️  {L('Skipped', 'Пропущен')}: {key}")
            continue

        try:
            files, data = runner(state)
            state.record(key, files, data)
            print(f"\n  ✅ {key.upper()} {L('done', 'завершён')}")
            for f in files[:2]:
                print(f"     📄 {f}")
        except FileNotFoundError as e:
            state.fail(key, str(e))
            print(f"\n  ❌ {e}")
            if not auto:
                if ask("Continue? (y/n): ", "Продолжить? (y/n): ") not in ("y", "yes", "да"):
                    break
        except Exception as e:
            state.fail(key, str(e))
            print(f"\n  ❌ {key}: {e}")

    # Summary
    header(L("Workflow Complete", "Воркфлоу завершён"))
    if state.completed:
        print(f"  ✅ {L('Done', 'Выполнено')}: {', '.join(state.completed)}")
    if state.skipped:
        print(f"  ⏭️  {L('Skipped', 'Пропущено')}: {', '.join(state.skipped)}")
    if state.errors:
        print(f"  ❌ {L('Errors', 'Ошибки')}: {', '.join(state.errors.keys())}")

    log_file = save_session(state)
    print(f"\n  💾 {log_file}")
    return state


def print_status() -> None:
    """Show latest output file from each agent."""
    header(L("System Status", "Статус системы"))
    checks = [
        ("CR",          "cr",          "cr_digest_*.md"),
        ("Discovery",   "discovery",   "discovery_report*.md"),
        ("PRD",         "prd",         "prd_*.md"),
        ("Grooming",    "grooming",    "grooming_report_*.md"),
        ("Planning",    "planning",    "sprint_plan_*.md"),
        ("Retro",       "retro",       "retro_report_*.md"),
        ("A/B Testing", "ab",          "ab_report_*.md"),
        ("Stakeholder", "stakeholder", "stakeholder_*.md"),
    ]
    for label, key, glob in checks:
        f = find_latest(glob, agent_dirs(key))
        if f:
            ts = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"\n  ✅ {label:<14} {f.name[:44]:<46} {ts}")
        else:
            print(f"\n  ⬜ {label:<14} {L('no output yet', 'нет вывода')}")

    cr_db = find_latest("cr_signals.db", agent_dirs("cr"))
    if cr_db:
        try:
            conn = sqlite3.connect(str(cr_db))
            n_sig = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
            n_opp = conn.execute(
                "SELECT COUNT(*) FROM opportunities WHERE status='open'"
            ).fetchone()[0]
            conn.close()
            print(f"\n  📊 CR DB: {n_sig} {L('signals', 'сигналов')} | "
                  f"{n_opp} {L('open opportunities', 'открытых возможностей')}")
        except Exception:
            pass


def interactive_menu() -> tuple[str, bool]:
    print(f"\n{L('Choose workflow:', 'Выбери воркфлоу:')}")
    for i, wf in enumerate(WORKFLOWS, 1):
        steps = WORKFLOW_STEPS[wf]
        chain = " → ".join(k.upper() for k, *_ in steps)
        print(f"  {i}. {wf.replace('_', ' ').title()}")
        print(f"     {chain}")

    choice = input(f"\n{L('Select (1-4): ', 'Выбери (1-4): ')}").strip()
    idx = (int(choice) - 1) if choice.isdigit() and 1 <= int(choice) <= 4 else 0
    workflow = WORKFLOWS[idx]

    mode = ask(
        "Mode: a — auto | i — interactive (default): ",
        "Режим: a — авто | i — интерактивный (по умолчанию): ",
    )
    return workflow, mode == "a"


# ─────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────

def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="PM Agent Orchestrator")
    p.add_argument("--lang",     choices=["en", "ru"])
    p.add_argument("--workflow", choices=WORKFLOWS)
    p.add_argument("--auto",     action="store_true")
    p.add_argument("--status",   action="store_true")
    p.add_argument("--session",  type=str)
    args = p.parse_args()

    if args.lang:
        set_language(args.lang)

    if args.status:
        print_status()
        return

    workflow, auto = (args.workflow, args.auto) if args.workflow else interactive_menu()
    run_workflow(workflow, session_id=args.session, auto=auto)


if __name__ == "__main__":
    main()
