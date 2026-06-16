# Testing Patterns

**Analysis Date:** 2026-06-16

## Test Framework

**Runner:**
- pytest (version not pinned in `app/requirements.txt` — `pywebview>=5.0`, `playwright>=1.40`, `pyinstaller>=6.0` are the only listed deps; pytest pulled as dev dependency)
- No `pytest.ini`, `setup.cfg`, or `pyproject.toml` found — pytest runs with defaults
- Config: none detected

**Assertion Library:**
- pytest built-in `assert` statements — no third-party assertion library

**Mocking:**
- `unittest.mock.patch` from standard library

**Run Commands:**
```bash
pytest tests/                  # Run all tests
pytest tests/test_report_editor.py  # Run single file
pytest -v tests/               # Verbose output
```

## Test File Organization

**Location:**
- Separate `tests/` directory at repo root
- `tests/__init__.py` present (empty — marks as package for import resolution)

**Naming:**
- Test files: `test_<subject>.py` — e.g., `test_report_editor.py`
- Test classes: `Test<Feature>` — e.g., `TestSaveReport`, `TestStepFields`, `TestReportCRUD`
- Test functions: `test_<behavior>` — e.g., `test_save_new_report_sets_version_1`, `test_toggle_report`

**Structure:**
```
tests/
├── __init__.py
└── test_report_editor.py
```

Only one test file exists covering `PipelineAPI` methods from `app/main.py`.

## Test Structure

**Suite Organization:**
```python
class TestSaveReport:
    def test_save_new_report_sets_version_1(self, api): ...
    def test_save_existing_report_increments_version(self, api): ...

class TestStepFields:
    """Verify all PRD-required step fields are preserved through save/load."""
    def test_display_label_persisted(self, api): ...

class TestReportCRUD:
    def test_get_reports_lists_all(self, api): ...
```

Tests are organized into classes by feature area. Each class covers one logical capability.

**Patterns:**
- Setup: pytest fixture `api` creates a `PipelineAPI` wired to `tmp_path` (pytest's built-in temp dir fixture)
- No teardown needed — `tmp_path` is automatically cleaned up by pytest
- Assertions use plain `assert` — boolean, equality (`==`), identity (`is`), membership (`in`), `is None`

## Mocking

**Framework:** `unittest.mock.patch` (standard library)

**Patterns:**
```python
# Patch internal path resolver to redirect config to tmp_path
with patch("app.main._user_config_path", return_value=config_file):
    from app.main import PipelineAPI
    instance = PipelineAPI()
    yield instance

# Patch env expansion for cross-platform path tests
monkeypatch.setenv("USERPROFILE", "C:\\Users\\Andrew")
monkeypatch.setattr("execution.download_reports.os.path.expandvars", ntpath.expandvars)
```

**What is mocked:**
- `app.main._user_config_path` — redirects config file location to `tmp_path` so tests don't touch user's real config
- `os.path.expandvars` — patched to `ntpath.expandvars` in Windows path edge-case tests running on non-Windows
- `USERPROFILE` env var — set via `monkeypatch.setenv` for path expansion tests

**What is NOT mocked:**
- File I/O — tests write real JSON config to `tmp_path` and read it back
- `PipelineAPI` business logic — tested through the real implementation
- No network mocking — no network calls in unit tests

## Fixtures and Factories

**Primary Fixture:**
```python
@pytest.fixture()
def api(tmp_path):
    """Create a PipelineAPI wired to a temp config directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "browser_config.json"

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
```

**Location:** `tests/test_report_editor.py` — fixtures defined at module level in the same file as tests

**Minimal config seed:** Tests use a minimal valid JSON config object — only required fields populated, no optional fields

## Coverage

**Requirements:** None enforced — no coverage configuration found

**View Coverage:**
```bash
pytest --cov=app --cov=execution tests/
```
(requires `pytest-cov` installed separately)

## Test Types

**Unit Tests:**
- `tests/test_report_editor.py` — covers `PipelineAPI` CRUD methods: `save_report`, `get_report_detail`, `get_reports`, `toggle_report`, `remove_report`
- Also covers `execution.build_ryan_report.build_serial_lookup` (pure function, no I/O)
- Also covers `execution.download_reports.load_config` (file I/O, monkeypatched)

**Integration Tests:** Not present as a separate category — the unit tests use real file I/O via `tmp_path`, making them lightweight integration tests in practice

**E2E Tests:** Not used — Playwright is a listed dependency but no Playwright test files found

## Common Patterns

**Parametrize for action-type coverage:**
```python
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
```

**Cross-platform path testing:**
```python
def test_download_loader_preserves_password_with_dollar_signs(
    self, tmp_path, monkeypatch
):
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\Andrew")
    monkeypatch.setattr("execution.download_reports.os.path.expandvars", ntpath.expandvars)
    from execution.download_reports import load_config
    cfg = load_config(config_file)
    assert cfg["auth"]["password"] == "secret$$"
```

**Deferred imports inside tests:** Modules are imported inside test functions (not at module top) when they depend on patched state — this is critical because `PipelineAPI` reads config at instantiation time and the patch must be active at import+instantiation.

---

*Testing analysis: 2026-06-16*
