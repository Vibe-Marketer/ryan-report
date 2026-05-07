"""Tests for the report path editor API methods in PipelineAPI."""
from __future__ import annotations

import json
import ntpath
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure the app package is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def api(tmp_path):
    """Create a PipelineAPI wired to a temp config directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "browser_config.json"

    # Seed a minimal valid config.
    config_file.write_text(json.dumps({
        "auth": {"base_url": "https://test.axoneta.io/", "username": "u", "password": "p"},
        "browser": {"executable_path": "/usr/bin/true", "user_data_dir": str(tmp_path)},
        "downloads": {"directory": str(tmp_path / "dl")},
        "reports": [],
    }))

    with patch("app.main._user_config_path", return_value=config_file):
        from app.main import PipelineAPI
        instance = PipelineAPI()
        yield instance


class TestSaveReport:
    def test_save_new_report_sets_version_1(self, api):
        report = {
            "name": "test_report",
            "steps": [
                {"action": "click_tab", "label": "Tab", "name": "Contents", "wait_ms": 1000,
                 "triggers_download": False},
            ],
        }
        result = api.save_report(report)
        assert result == "ok"

        detail = api.get_report_detail("test_report")
        assert detail is not None
        assert detail["version"] == 1
        assert detail["enabled"] is True

    def test_save_existing_report_increments_version(self, api):
        report = {"name": "r1", "steps": [{"action": "click_tab", "name": "X"}]}
        api.save_report(report)
        api.save_report({"name": "r1", "steps": [{"action": "click_tab", "name": "Y"}]})

        detail = api.get_report_detail("r1")
        assert detail["version"] == 2

    def test_save_report_requires_name(self, api):
        result = api.save_report({"name": "", "steps": []})
        assert "error" in result

    def test_save_normalizes_step_fields(self, api):
        report = {
            "name": "norm",
            "steps": [
                {"action": "click_tab", "text": "Trucking"},
                {"action": "click_menu"},
                {"action": "click_button", "name": "Export", "triggers_download": True},
            ],
        }
        api.save_report(report)
        detail = api.get_report_detail("norm")
        steps = detail["steps"]

        # click_tab: should have 'name' populated from 'text'
        assert steps[0]["name"] == "Trucking"
        # All steps should have triggers_download
        assert steps[1]["triggers_download"] is False
        # click_button: should have 'text' populated from 'name'
        assert steps[2]["text"] == "Export"
        assert steps[2]["triggers_download"] is True


class TestStepFields:
    """Verify all PRD-required step fields are preserved through save/load."""

    def test_display_label_persisted(self, api):
        report = {
            "name": "label_test",
            "steps": [{"action": "click_tab", "label": "My Label", "name": "Tab1", "wait_ms": 500}],
        }
        api.save_report(report)
        detail = api.get_report_detail("label_test")
        assert detail["steps"][0]["label"] == "My Label"

    def test_target_text_name_persisted(self, api):
        report = {
            "name": "target_test",
            "steps": [
                {"action": "click_tab", "label": "T", "name": "Contents"},
                {"action": "click_menu", "label": "M", "text": "Reporter Reports"},
            ],
        }
        api.save_report(report)
        detail = api.get_report_detail("target_test")
        assert detail["steps"][0]["name"] == "Contents"
        assert detail["steps"][1]["text"] == "Reporter Reports"

    def test_triggers_download_persisted(self, api):
        report = {
            "name": "dl_test",
            "steps": [
                {"action": "click_tab", "name": "X", "triggers_download": False},
                {"action": "click_button", "text": "Export", "triggers_download": True, "timeout_ms": 60000},
            ],
        }
        api.save_report(report)
        detail = api.get_report_detail("dl_test")
        assert detail["steps"][0]["triggers_download"] is False
        assert detail["steps"][1]["triggers_download"] is True
        assert detail["steps"][1].get("timeout_ms") == 60000

    def test_wait_ms_persisted(self, api):
        report = {
            "name": "wait_test",
            "steps": [{"action": "click_tab", "name": "X", "wait_ms": 3500}],
        }
        api.save_report(report)
        detail = api.get_report_detail("wait_test")
        assert detail["steps"][0]["wait_ms"] == 3500


class TestReportCRUD:
    def test_get_reports_lists_all(self, api):
        api.save_report({"name": "a", "steps": []})
        api.save_report({"name": "b", "steps": []})
        reports = api.get_reports()
        names = [r["name"] for r in reports]
        assert "a" in names
        assert "b" in names

    def test_toggle_report(self, api):
        api.save_report({"name": "t", "steps": []})
        api.toggle_report("t", False)
        reports = api.get_reports()
        t = next(r for r in reports if r["name"] == "t")
        assert t["enabled"] is False

    def test_remove_report(self, api):
        api.save_report({"name": "rm_me", "steps": []})
        api.remove_report("rm_me")
        assert api.get_report_detail("rm_me") is None

    def test_get_report_detail_not_found(self, api):
        assert api.get_report_detail("nonexistent") is None


class TestStepTypes:
    """Verify all v1 step types are supported."""

    @pytest.mark.parametrize(
        "action",
        ["click_tab", "click_menu", "click_button", "set_end_date_today"],
    )
    def test_supported_step_types(self, api, action):
        report = {
            "name": f"type_{action}",
            "steps": [{"action": action, "label": "L", "name": "N", "text": "T"}],
        }
        result = api.save_report(report)
        assert result == "ok"
        detail = api.get_report_detail(f"type_{action}")
        assert detail["steps"][0]["action"] == action

    def test_date_step_cannot_trigger_download(self, api):
        report = {
            "name": "date_step",
            "steps": [{"action": "set_end_date_today", "triggers_download": True}],
        }
        api.save_report(report)
        detail = api.get_report_detail("date_step")
        assert detail["steps"][0]["triggers_download"] is False


class TestConfigExpansion:
    def test_app_load_config_preserves_password_with_dollar_signs(
        self, tmp_path, monkeypatch
    ):
        config_file = tmp_path / "browser_config.json"
        config_file.write_text(json.dumps({
            "auth": {
                "base_url": "https://test.axoneta.io/",
                "username": "u",
                "password": "secret$$",
            },
            "downloads": {"directory": "%USERPROFILE%\\Downloads"},
        }))

        monkeypatch.setenv("USERPROFILE", "C:\\Users\\Andrew")
        monkeypatch.setattr("app.main.os.path.expandvars", ntpath.expandvars)

        with patch("app.main._user_config_path", return_value=config_file):
            from app.main import PipelineAPI
            cfg = PipelineAPI().load_config()

        assert cfg["auth"]["password"] == "secret$$"
        assert cfg["downloads"]["directory"] == "C:\\Users\\Andrew\\Downloads"


class TestSerialLookup:
    def test_generated_lookup_seeds_historical_and_overrides_win(self):
        from execution.build_ryan_report import build_serial_lookup

        lookup = build_serial_lookup(
            {"S1": {"description": "Seed", "meter": "1"}},
            {"S2": {"description": "Historical", "meter": "2"}},
            {"S1": {"description": "Override", "meter": "3"}},
        )

        assert lookup["S1"]["description"] == "Override"
        assert lookup["S1"]["meter"] == "3"
        assert lookup["S2"]["description"] == "Historical"

    def test_download_loader_preserves_password_with_dollar_signs(
        self, tmp_path, monkeypatch
    ):
        config_file = tmp_path / "browser_config.json"
        config_file.write_text(json.dumps({
            "auth": {
                "base_url": "https://test.axoneta.io/",
                "username": "u",
                "password": "secret$$",
            },
            "downloads": {"directory": "%USERPROFILE%\\Downloads"},
        }))

        monkeypatch.setenv("USERPROFILE", "C:\\Users\\Andrew")
        monkeypatch.setattr("execution.download_reports.os.path.expandvars", ntpath.expandvars)

        from execution.download_reports import load_config
        cfg = load_config(config_file)

        assert cfg["auth"]["password"] == "secret$$"
        assert cfg["downloads"]["directory"] == "C:\\Users\\Andrew\\Downloads"
