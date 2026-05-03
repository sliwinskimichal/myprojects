"""Tests for engine/config.py — config loading, env override, defaults."""

from __future__ import annotations
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.config import _load_toml, _merge, load, Config
from pathlib import Path


class TestLoadToml(unittest.TestCase):
    def test_nonexistent_file_returns_empty(self):
        tmp = Path(tempfile.mkdtemp()) / "missing.toml"
        self.assertEqual(_load_toml(tmp), {})

    def test_loads_valid_toml(self):
        tmp = Path(tempfile.mkdtemp()) / "test.toml"
        tmp.write_text('[api]\ndaily_budget_usd = 2.5\n')
        result = _load_toml(tmp)
        self.assertAlmostEqual(result["api"]["daily_budget_usd"], 2.5)

    def test_handles_nested_sections(self):
        tmp = Path(tempfile.mkdtemp()) / "test.toml"
        tmp.write_text('[db]\nsqlite_path = "custom.db"\n')
        result = _load_toml(tmp)
        self.assertEqual(result["db"]["sqlite_path"], "custom.db")


class TestMerge(unittest.TestCase):
    def test_base_values_kept(self):
        result = _merge({"a": 1, "b": 2}, {"b": 99})
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"], 99)

    def test_nested_merge(self):
        base     = {"api": {"key": "old", "budget": 1.0}}
        override = {"api": {"budget": 5.0}}
        result   = _merge(base, override)
        self.assertEqual(result["api"]["key"],    "old")
        self.assertAlmostEqual(result["api"]["budget"], 5.0)

    def test_override_wins_for_scalars(self):
        self.assertEqual(_merge({"x": 1}, {"x": 2})["x"], 2)

    def test_empty_override_preserves_base(self):
        self.assertEqual(_merge({"x": 1}, {}), {"x": 1})

    def test_empty_base(self):
        self.assertEqual(_merge({}, {"y": 42})["y"], 42)


class TestLoadEnvOverrides(unittest.TestCase):
    """Test that environment variables override file values."""

    def _clear_env(self):
        for var in [
            "ANTHROPIC_API_KEY", "DAILY_BUDGET_USD",
            "DEFAULT_CONTEXT", "SQLITE_PATH", "CHROMA_PATH",
            "NIGHT_WATCH_TIME",
        ]:
            os.environ.pop(var, None)

    def setUp(self):
        self._clear_env()

    def tearDown(self):
        self._clear_env()

    def test_returns_config_instance(self):
        self.assertIsInstance(load(), Config)

    def test_env_api_key_override(self):
        os.environ["ANTHROPIC_API_KEY"] = "test-key-123"
        self.assertEqual(load().api.anthropic_api_key, "test-key-123")

    def test_env_budget_override(self):
        os.environ["DAILY_BUDGET_USD"] = "3.14"
        self.assertAlmostEqual(load().api.daily_budget_usd, 3.14, places=5)

    def test_env_context_override(self):
        os.environ["DEFAULT_CONTEXT"] = "Software_House"
        self.assertEqual(load().app.default_context, "Software_House")

    def test_env_sqlite_path_override(self):
        os.environ["SQLITE_PATH"] = "/tmp/custom.db"
        self.assertEqual(load().db.sqlite_path, "/tmp/custom.db")

    def test_defaults_when_no_env(self):
        cfg = load()
        self.assertAlmostEqual(cfg.api.daily_budget_usd, 1.0)
        self.assertEqual(cfg.app.default_context, "HR_Office")

    def test_limits_section_positive(self):
        cfg = load()
        self.assertGreater(cfg.limits.max_tokens_default, 0)
        self.assertGreater(cfg.limits.max_tokens_short,   0)

    def test_limits_short_less_than_default(self):
        cfg = load()
        self.assertLess(cfg.limits.max_tokens_short, cfg.limits.max_tokens_default)

    def test_demo_interval_positive(self):
        cfg = load()
        self.assertGreater(cfg.app.demo_interval, 0)


if __name__ == "__main__":
    unittest.main()
