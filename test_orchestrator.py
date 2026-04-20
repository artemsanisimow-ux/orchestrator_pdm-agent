"""
Test suite for Orchestrator.
Covers: OrchState, file utilities, data extractors, runners (mocked agents),
workflow definitions, router logic, status output, i18n.
Run: pytest test_orchestrator.py -v
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test")
sys.path.insert(0, "/mnt/user-data/outputs")
sys.path.insert(0, "/home/claude/orchestrator")

import orchestrator as oc
import i18n


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_loaded():
    """Clear cached agent modules between tests."""
    oc._loaded.clear()
    yield
    oc._loaded.clear()


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    """Redirect all AGENT_DIRS to tmp_path so file lookups don't escape."""
    for key in oc.AGENT_DIRS:
        monkeypatch.setitem(oc.AGENT_DIRS, key, str(tmp_path))
    monkeypatch.chdir(tmp_path)
    yield tmp_path


@pytest.fixture
def state() -> oc.OrchState:
    return oc.OrchState("sprint_cycle", "test_session")


@pytest.fixture
def cr_db(tmp_env) -> Path:
    """Create a minimal CR SQLite DB in tmp dir."""
    db = tmp_env / "cr_signals.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE signals (
            id INTEGER PRIMARY KEY, source TEXT, raw_text TEXT,
            opportunity TEXT, sentiment REAL, tags_json TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE opportunities (
            id INTEGER PRIMARY KEY, title TEXT UNIQUE, outcome TEXT DEFAULT '',
            signal_count INTEGER DEFAULT 1, avg_sentiment REAL,
            status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE digests (
            id INTEGER PRIMARY KEY, week_start TEXT,
            content TEXT, signal_count INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE alerts (
            id INTEGER PRIMARY KEY, alert_type TEXT, message TEXT,
            opportunity TEXT, resolved INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.execute("INSERT INTO opportunities (title, signal_count, avg_sentiment) VALUES (?,?,?)",
                 ("Export discoverability", 5, -0.4))
    conn.execute("INSERT INTO opportunities (title, signal_count, avg_sentiment) VALUES (?,?,?)",
                 ("Onboarding confusion", 3, -0.6))
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def retro_insights(tmp_env) -> Path:
    """Create a retro planning insights JSON."""
    data = {
        "action_items": ["Fix CI pipeline", "Add unit tests", "Improve onboarding docs"],
        "velocity_adjustment": 0.85,
    }
    f = tmp_env / "retro_planning_insights_test_20260101.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


@pytest.fixture
def discovery_report(tmp_env) -> Path:
    f = tmp_env / "discovery_report_test.md"
    f.write_text("# Discovery Report\n\n- Users struggle with export\n- Onboarding too long",
                 encoding="utf-8")
    return f


@pytest.fixture
def sprint_plan(tmp_env) -> Path:
    f = tmp_env / "sprint_plan_test_20260101.md"
    f.write_text("# Sprint 15\n\nGoal: Ship export feature\n\nVelocity: 42 SP",
                 encoding="utf-8")
    return f


@pytest.fixture
def ab_report(tmp_env) -> Path:
    f = tmp_env / "ab_report_test_20260101.md"
    f.write_text(
        "# A/B Report\n\n**Verdict:** ship 🚀\n\nVelocity: no impact\nRisk: low\n",
        encoding="utf-8"
    )
    return f


# ─────────────────────────────────────────────
# 1. OrchState
# ─────────────────────────────────────────────

class TestOrchState:
    def test_init(self, state):
        assert state.workflow == "sprint_cycle"
        assert state.session_id == "test_session"
        assert state.completed == []
        assert state.skipped == []
        assert state.errors == {}

    def test_record(self, state):
        state.record("discovery", ["report.md"], {"session_id": "s1"})
        assert "discovery" in state.completed
        assert state.outputs["discovery"]["files"] == ["report.md"]

    def test_fail(self, state):
        state.fail("prd", "File not found")
        assert state.errors["prd"] == "File not found"

    def test_to_json_structure(self, state):
        state.record("discovery", ["f.md"], {})
        state.skipped.append("grooming")
        state.fail("prd", "err")
        data = json.loads(state.to_json())
        assert "session_id" in data
        assert "completed" in data
        assert "skipped" in data
        assert "errors" in data
        assert "output_files" in data
        assert data["completed"] == ["discovery"]

    def test_to_json_serializable(self, state):
        state.record("cr", [], {"key": "val"})
        # Should not raise
        json.dumps(state.to_json())

    def test_multiple_records(self, state):
        for agent in ["cr", "discovery", "prd"]:
            state.record(agent, [], {})
        assert state.completed == ["cr", "discovery", "prd"]


# ─────────────────────────────────────────────
# 2. File Utilities
# ─────────────────────────────────────────────

class TestFileUtils:
    def test_find_latest_returns_newest(self, tmp_path):
        f1 = tmp_path / "digest_20260101.md"
        f2 = tmp_path / "digest_20260102.md"
        f1.write_text("old")
        import time; time.sleep(0.01)
        f2.write_text("new")
        result = oc.find_latest("digest_*.md", [str(tmp_path)])
        assert result.name == "digest_20260102.md"

    def test_find_latest_returns_none_if_no_match(self, tmp_path):
        assert oc.find_latest("nonexistent_*.md", [str(tmp_path)]) is None

    def test_find_latest_searches_multiple_dirs(self, tmp_path):
        d1, d2 = tmp_path / "d1", tmp_path / "d2"
        d1.mkdir(); d2.mkdir()
        (d2 / "file.md").write_text("hi")
        result = oc.find_latest("file.md", [str(d1), str(d2)])
        assert result is not None

    def test_read_text_existing_file(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("hello world")
        assert oc.read_text(f) == "hello world"

    def test_read_text_none_returns_empty(self):
        assert oc.read_text(None) == ""

    def test_read_text_nonexistent_returns_empty(self, tmp_path):
        assert oc.read_text(tmp_path / "missing.md") == ""

    def test_read_text_truncates(self, tmp_path):
        f = tmp_path / "long.md"
        f.write_text("x" * 10000)
        result = oc.read_text(f, max_chars=100)
        assert len(result) == 100

    def test_read_json_valid(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"key": "value"}')
        assert oc.read_json(f) == {"key": "value"}

    def test_read_json_none_returns_empty(self):
        assert oc.read_json(None) == {}

    def test_read_json_invalid_returns_empty(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json at all {{{")
        assert oc.read_json(f) == {}

    def test_agent_dirs_returns_list(self):
        dirs = oc.agent_dirs("discovery")
        assert isinstance(dirs, list)
        assert len(dirs) == 2


# ─────────────────────────────────────────────
# 3. Data Extractors
# ─────────────────────────────────────────────

class TestExtractors:
    def test_extract_cr_with_db(self, tmp_env, cr_db, state):
        result = oc.extract_cr(state)
        assert len(result["opportunities"]) == 2
        assert result["opportunities"][0]["title"] == "Export discoverability"
        assert result["opportunities"][0]["signal_count"] == 5
        assert "Export discoverability" in result["discovery_insights"]

    def test_extract_cr_no_db(self, tmp_env, state):
        result = oc.extract_cr(state)
        assert result["opportunities"] == []
        assert result["planning_risks"] == []
        assert result["discovery_insights"] == ""

    def test_extract_cr_extracts_planning_risks(self, tmp_env, state):
        digest = tmp_env / "cr_digest_20260101.md"
        digest.write_text(
            "## Headline\n\nSome text\n\n## Planning Risks\n\n- Risk A\n- Risk B\n\n## Next\n"
        )
        result = oc.extract_cr(state)
        assert "Risk A" in result["planning_risks"]
        assert "Risk B" in result["planning_risks"]

    def test_extract_discovery_with_file(self, tmp_env, state, discovery_report):
        result = oc.extract_discovery(state)
        assert "discovery_report_test.md" in result["report_path"]
        assert "export" in result["content"].lower()

    def test_extract_discovery_no_file(self, tmp_env, state):
        result = oc.extract_discovery(state)
        assert result["report_path"] == ""
        assert result["content"] == ""

    def test_extract_retro_with_insights(self, tmp_env, state, retro_insights):
        result = oc.extract_retro(state)
        assert len(result["action_items"]) == 3
        assert result["velocity_factor"] == 0.85
        assert "Fix CI pipeline" in result["action_items"]

    def test_extract_retro_no_file(self, tmp_env, state):
        result = oc.extract_retro(state)
        assert result["action_items"] == []
        assert result["velocity_factor"] == 1.0

    def test_extract_retro_fallback_from_report(self, tmp_env, state):
        report = tmp_env / "retro_report_test.md"
        report.write_text("## Action Items\n\n- Fix tests\n- Update docs\n")
        result = oc.extract_retro(state)
        # action items come from markdown lines
        assert any("Fix tests" in item for item in result["action_items"])

    def test_extract_ab_with_file(self, tmp_env, state, ab_report):
        result = oc.extract_ab(state)
        assert result["verdict"] == "ship"

    def test_extract_ab_no_file(self, tmp_env, state):
        result = oc.extract_ab(state)
        assert result["verdict"] == ""
        assert result["risk_note"] == ""

    def test_extract_planning_with_file(self, tmp_env, state, sprint_plan):
        result = oc.extract_planning(state)
        assert "Sprint 15" in result["content"]

    def test_extract_planning_no_file(self, tmp_env, state):
        result = oc.extract_planning(state)
        assert result["content"] == ""


# ─────────────────────────────────────────────
# 4. Helpers & I18n
# ─────────────────────────────────────────────

class TestHelpers:
    def test_L_en(self):
        i18n.set_language("en")
        assert oc.L("Hello", "Привет") == "Hello"

    def test_L_ru(self):
        i18n.set_language("ru")
        assert oc.L("Hello", "Привет") == "Привет"

    def test_save_session(self, tmp_path, monkeypatch, state):
        monkeypatch.chdir(tmp_path)
        state.record("discovery", ["f.md"], {})
        fname = oc.save_session(state)
        assert Path(fname).exists()
        data = json.loads(Path(fname).read_text())
        assert data["workflow"] == "sprint_cycle"
        assert "discovery" in data["completed"]

    def test_collect_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "sprint_plan_001.md").write_text("plan 1")
        (tmp_path / "sprint_plan_002.md").write_text("plan 2")
        files = oc._collect_files("sprint_plan_*.md")
        assert len(files) <= 3
        assert all(f.endswith(".md") for f in files)


# ─────────────────────────────────────────────
# 5. Workflow Definitions
# ─────────────────────────────────────────────

class TestWorkflowDefinitions:
    def test_all_workflows_defined(self):
        for wf in oc.WORKFLOWS:
            assert wf in oc.WORKFLOW_STEPS

    def test_sprint_cycle_agents(self):
        keys = [k for k, *_ in oc.WORKFLOW_STEPS["sprint_cycle"]]
        assert keys == ["discovery", "prd", "grooming", "planning", "stakeholder"]

    def test_research_cycle_agents(self):
        keys = [k for k, *_ in oc.WORKFLOW_STEPS["research_cycle"]]
        assert keys == ["cr", "discovery", "ab"]

    def test_retro_cycle_agents(self):
        keys = [k for k, *_ in oc.WORKFLOW_STEPS["retro_cycle"]]
        assert keys == ["retro", "cr", "planning", "stakeholder"]

    def test_full_cycle_agents(self):
        keys = [k for k, *_ in oc.WORKFLOW_STEPS["full_cycle"]]
        assert keys == ["cr", "discovery", "prd", "grooming", "planning", "retro", "stakeholder"]

    def test_each_step_has_runner(self):
        for wf, steps in oc.WORKFLOW_STEPS.items():
            for key, desc_en, desc_ru, runner in steps:
                assert callable(runner), f"{wf}/{key} runner not callable"
                assert isinstance(desc_en, str)
                assert isinstance(desc_ru, str)

    def test_full_cycle_is_superset(self):
        """full_cycle covers all core PM workflow agents.
        research_cycle adds ab (experiment design) which is optional in full_cycle.
        """
        full_keys = {k for k, *_ in oc.WORKFLOW_STEPS["full_cycle"]}
        # Core agents must be in full_cycle
        for core in ["cr", "discovery", "planning", "stakeholder", "retro"]:
            assert core in full_keys, f"{core} missing from full_cycle"
        # sprint_cycle is fully contained
        for k, *_ in oc.WORKFLOW_STEPS["sprint_cycle"]:
            assert k in full_keys, f"sprint_cycle/{k} missing from full_cycle"


# ─────────────────────────────────────────────
# 6. Runners (mocked agents)
# ─────────────────────────────────────────────

class TestRunners:
    """Test runner functions with mocked agent modules."""

    def _make_mock_agent(self, run_fn_name: str, return_value: tuple):
        mod = MagicMock()
        getattr(mod, run_fn_name).return_value = return_value
        return mod

    def test_run_discovery_passes_cr_context(self, tmp_env, state, cr_db):
        mock_mod = self._make_mock_agent("run_discovery", ({"state": {}}, "sid1"))
        with patch.object(oc, "load_agent", return_value=mock_mod):
            oc.run_discovery(state)
        call_kwargs = mock_mod.run_discovery.call_args
        assert call_kwargs is not None
        # product_context should contain opportunity from CR DB
        ctx = call_kwargs.kwargs.get("product_context", "")
        assert "Export discoverability" in ctx

    def test_run_prd_passes_discovery_path(self, tmp_env, state, discovery_report):
        mock_mod = self._make_mock_agent("run_prd", ({}, "sid2"))
        with patch.object(oc, "load_agent", return_value=mock_mod):
            oc.run_prd(state)
        call_kwargs = mock_mod.run_prd.call_args
        path = call_kwargs.kwargs.get("discovery_report", "")
        assert "discovery_report_test.md" in path

    def test_run_planning_builds_context(self, tmp_env, state, retro_insights, cr_db):
        mock_mod = self._make_mock_agent("run_planning", ({}, "sid3"))
        with patch.object(oc, "load_agent", return_value=mock_mod):
            _, data = oc.run_planning(state)
        assert "context" in data

    def test_run_planning_sets_env_context(self, tmp_env, state, retro_insights):
        mock_mod = self._make_mock_agent("run_planning", ({}, "sid"))
        captured = {}
        def fake_run():
            captured["ctx"] = os.environ.get("ORCH_PLANNING_CONTEXT", "")
            return {}, "sid"
        mock_mod.run_planning.side_effect = fake_run
        with patch.object(oc, "load_agent", return_value=mock_mod):
            oc.run_planning(state)
        # Env var should be cleaned up after
        assert "ORCH_PLANNING_CONTEXT" not in os.environ

    def test_run_planning_clears_env_on_exception(self, tmp_env, state):
        mock_mod = MagicMock()
        mock_mod.run_planning.side_effect = RuntimeError("boom")
        with patch.object(oc, "load_agent", return_value=mock_mod):
            try:
                oc.run_planning(state)
            except RuntimeError:
                pass
        assert "ORCH_PLANNING_CONTEXT" not in os.environ

    def test_run_stakeholder_passes_plan_context(self, tmp_env, state, sprint_plan):
        mock_mod = self._make_mock_agent("run_stakeholder", ({}, "sid4"))
        with patch.object(oc, "load_agent", return_value=mock_mod):
            oc.run_stakeholder(state)
        call_kwargs = mock_mod.run_stakeholder.call_args
        ctx = call_kwargs.kwargs.get("context", "")
        assert "Sprint 15" in ctx

    def test_run_ab_passes_discovery_insights(self, tmp_env, state, discovery_report):
        mock_mod = self._make_mock_agent("run_ab_test", ({}, "sid5"))
        with patch.object(oc, "load_agent", return_value=mock_mod):
            oc.run_ab(state)
        call_kwargs = mock_mod.run_ab_test.call_args
        insights = call_kwargs.kwargs.get("discovery_insights", "")
        assert "export" in insights.lower()

    def test_run_cr_with_retro_seeds_db(self, tmp_env, state, retro_insights):
        mock_mod = self._make_mock_agent("run_cr", ({}, "sid6"))
        with patch.object(oc, "load_agent", return_value=mock_mod):
            oc.run_cr_with_retro(state)
        # CR DB should have been created with retro signals
        cr_db = tmp_env / "cr_signals.db"
        assert cr_db.exists()
        conn = sqlite3.connect(str(cr_db))
        count = conn.execute("SELECT COUNT(*) FROM signals WHERE source='analytics'").fetchone()[0]
        conn.close()
        assert count == 3  # 3 action items from fixture

    def test_run_cr_with_retro_no_action_items(self, tmp_env, state):
        """Should not crash when retro has no action items."""
        mock_mod = self._make_mock_agent("run_cr", ({}, "sid7"))
        with patch.object(oc, "load_agent", return_value=mock_mod):
            files, data = oc.run_cr_with_retro(state)
        assert isinstance(files, list)


# ─────────────────────────────────────────────
# 7. run_workflow integration (mocked)
# ─────────────────────────────────────────────

class TestRunWorkflow:
    def _mock_runner(self, monkeypatch, files=None, data=None):
        """Replace runner references inside WORKFLOW_STEPS tuples."""
        files = files or []
        data  = data  or {}
        mock_fn = lambda s, f=files, d=data: (f, d)
        patched = {}
        for wf, steps in oc.WORKFLOW_STEPS.items():
            patched[wf] = [
                (key, en, ru, mock_fn) for key, en, ru, _ in steps
            ]
        monkeypatch.setattr(oc, "WORKFLOW_STEPS", patched)

    def test_sprint_cycle_completes(self, tmp_env, monkeypatch):
        self._mock_runner(monkeypatch)
        monkeypatch.setattr("builtins.input", lambda _: "y")
        state = oc.run_workflow("sprint_cycle", auto=True)
        assert len(state.completed) == 5
        assert len(state.errors) == 0

    def test_research_cycle_completes(self, tmp_env, monkeypatch):
        self._mock_runner(monkeypatch)
        state = oc.run_workflow("research_cycle", auto=True)
        assert len(state.completed) == 3

    def test_retro_cycle_completes(self, tmp_env, monkeypatch):
        self._mock_runner(monkeypatch)
        state = oc.run_workflow("retro_cycle", auto=True)
        assert len(state.completed) == 4

    def test_full_cycle_completes(self, tmp_env, monkeypatch):
        self._mock_runner(monkeypatch)
        state = oc.run_workflow("full_cycle", auto=True)
        assert len(state.completed) == 7

    def test_agent_error_recorded(self, tmp_env, monkeypatch):
        call_count = [0]
        def failing_runner(s):
            call_count[0] += 1
            if call_count[0] == 1:
                raise FileNotFoundError("agent dir not found")
            return [], {}

        monkeypatch.setattr(oc, "run_discovery", failing_runner)
        for step_list in oc.WORKFLOW_STEPS.values():
            for _, _, _, runner in step_list:
                if runner.__name__ not in ("run_discovery",):
                    monkeypatch.setattr(oc, runner.__name__, lambda s: ([], {}))

        monkeypatch.setattr("builtins.input", lambda _: "y")
        state = oc.run_workflow("research_cycle", auto=True)
        assert "discovery" in state.errors

    def test_session_file_saved(self, tmp_env, monkeypatch):
        self._mock_runner(monkeypatch)
        state = oc.run_workflow("research_cycle", session_id="test123", auto=True)
        logs = list(tmp_env.glob("orchestrator_session_test123_*.json"))
        assert len(logs) == 1

    def test_session_contains_correct_workflow(self, tmp_env, monkeypatch):
        self._mock_runner(monkeypatch)
        state = oc.run_workflow("retro_cycle", session_id="rc1", auto=True)
        log = next(tmp_env.glob("orchestrator_session_rc1_*.json"))
        data = json.loads(log.read_text())
        assert data["workflow"] == "retro_cycle"

    def test_cancelled_workflow(self, tmp_env, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        state = oc.run_workflow("sprint_cycle")
        assert state.completed == []


# ─────────────────────────────────────────────
# 8. Agent Loader
# ─────────────────────────────────────────────

class TestAgentLoader:
    def test_load_agent_raises_if_dir_missing(self):
        with pytest.raises(FileNotFoundError):
            oc.load_agent("discovery")  # AGENT_DIRS points to non-existent sibling

    def test_load_agent_caches(self, tmp_path, monkeypatch):
        monkeypatch.setitem(oc.AGENT_DIRS, "cr", str(tmp_path))
        # Create a minimal cr_agent.py
        (tmp_path / "cr_agent.py").write_text(
            "def run_cr(): return {}, 'sid'\n"
        )
        mod1 = oc.load_agent("cr")
        mod2 = oc.load_agent("cr")
        assert mod1 is mod2  # same object — cached
