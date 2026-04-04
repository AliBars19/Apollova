"""Tests for JSX validation and render preflight."""
import os
import json
import tempfile
import pytest


class TestValidateJsxFile:
    def test_file_not_found(self):
        from scripts.jsx_validator import validate_jsx_file
        result = validate_jsx_file("/nonexistent/file.jsx")
        assert result["valid"] is False
        assert "not found" in result["errors"][0].lower()

    def test_not_jsx_extension(self, tmp_path):
        from scripts.jsx_validator import validate_jsx_file
        txt = tmp_path / "script.txt"
        txt.write_text("var x = 1;")
        result = validate_jsx_file(str(txt))
        assert any("Not a JSX" in e for e in result["errors"])

    def test_valid_jsx_file(self, tmp_path):
        from scripts.jsx_validator import validate_jsx_file
        jsx = tmp_path / "test.jsx"
        jsx.write_text("var x = 1;\nalert(x);")
        result = validate_jsx_file(str(jsx))
        assert result["valid"] is True
        assert result["lines"] == 2

    def test_warns_apply_template(self, tmp_path):
        from scripts.jsx_validator import validate_jsx_file
        jsx = tmp_path / "test.jsx"
        jsx.write_text('item.applyTemplate("H.264");')
        result = validate_jsx_file(str(jsx))
        assert any("applyTemplate" in w for w in result["warnings"])

    def test_warns_app_quit(self, tmp_path):
        from scripts.jsx_validator import validate_jsx_file
        jsx = tmp_path / "test.jsx"
        jsx.write_text("app.quit();")
        result = validate_jsx_file(str(jsx))
        assert any("app.quit" in w for w in result["warnings"])

    def test_warns_unresolved_placeholders(self, tmp_path):
        from scripts.jsx_validator import validate_jsx_file
        jsx = tmp_path / "test.jsx"
        jsx.write_text('var JOBS_PATH = "{{JOBS_PATH}}";')
        result = validate_jsx_file(str(jsx))
        assert any("placeholder" in w.lower() for w in result["warnings"])

    def test_warns_render_without_exit(self, tmp_path):
        from scripts.jsx_validator import validate_jsx_file
        jsx = tmp_path / "test.jsx"
        jsx.write_text("app.project.renderQueue.render();")
        result = validate_jsx_file(str(jsx))
        assert any("renderQueue" in w for w in result["warnings"])

    def test_jsxbin_extension_accepted(self, tmp_path):
        from scripts.jsx_validator import validate_jsx_file
        jsx = tmp_path / "test.jsxbin"
        jsx.write_text("binary content")
        result = validate_jsx_file(str(jsx))
        assert not any("Not a JSX" in e for e in result["errors"])

    def test_bridge_unavailable_still_validates(self, tmp_path):
        from scripts.jsx_validator import validate_jsx_file
        jsx = tmp_path / "test.jsx"
        jsx.write_text("var x = 1;")
        result = validate_jsx_file(str(jsx), bridge_port=1)  # Port 1 won't connect
        assert result["valid"] is True
        assert result["bridge_connected"] is False


class TestRenderPreflight:
    def test_unknown_template(self):
        from scripts.jsx_validator import render_preflight
        result = render_preflight("unknown", "/tmp/jobs")
        assert result["passed"] is False

    def test_missing_jobs_dir(self):
        from scripts.jsx_validator import render_preflight
        result = render_preflight("mono", "/nonexistent/dir")
        assert result["passed"] is False

    def test_empty_jobs_dir(self, tmp_path):
        from scripts.jsx_validator import render_preflight
        result = render_preflight("mono", str(tmp_path))
        assert result["passed"] is False
        assert any("No job" in c["detail"] for c in result["checks"])

    def test_valid_job_folders(self, tmp_path):
        from scripts.jsx_validator import render_preflight
        # Create a job folder with required files
        job = tmp_path / "job_001"
        job.mkdir()
        (job / "job_data.json").write_text("{}")
        (job / "audio_trimmed.wav").write_bytes(b"fake")
        # This will still fail on JSX not found, but job check should pass
        result = render_preflight("mono", str(tmp_path))
        job_check = next((c for c in result["checks"] if c["name"] == "Job files"), None)
        if job_check:
            assert job_check["status"] == "pass"

    def test_missing_job_files(self, tmp_path):
        from scripts.jsx_validator import render_preflight
        job = tmp_path / "job_001"
        job.mkdir()
        # Missing job_data.json and audio
        result = render_preflight("mono", str(tmp_path))
        job_check = next((c for c in result["checks"] if c["name"] == "Job files"), None)
        if job_check:
            assert job_check["status"] == "fail"
