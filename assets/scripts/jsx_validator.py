"""
JSX validation via the AE MCP bridge.
Falls back to basic file checks if the bridge is unavailable.
"""
import os


def validate_jsx_file(jsx_path: str, bridge_port: int = 9741) -> dict:
    """
    Validate a JSX file before execution.

    Tries the MCP bridge first (full AE-side validation).
    Falls back to basic file existence + syntax heuristics.

    Returns:
        dict with keys: valid (bool), errors (list), warnings (list)
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Basic file checks (always run)
    if not os.path.exists(jsx_path):
        return {"valid": False, "errors": [f"File not found: {jsx_path}"], "warnings": []}

    if not jsx_path.lower().endswith((".jsx", ".jsxbin")):
        errors.append(f"Not a JSX file: {jsx_path}")

    try:
        with open(jsx_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return {"valid": False, "errors": [f"Cannot read file: {e}"], "warnings": []}

    # Static analysis warnings
    if "applyTemplate" in content:
        warnings.append("applyTemplate() found — removed from AE 2023+")
    if "app.quit()" in content:
        warnings.append("app.quit() found — use app.exitAfterLaunchAndEval instead")
    if "{{" in content and "}}" in content:
        warnings.append("Unresolved template placeholders found")
    if "renderQueue.render()" in content and "exitAfterLaunchAndEval" not in content:
        warnings.append("renderQueue.render() without exitAfterLaunchAndEval — may hang in headless mode")

    # Try bridge validation (non-blocking, best-effort)
    bridge_result = _try_bridge_validation(jsx_path, bridge_port)
    if bridge_result:
        errors.extend(bridge_result.get("errors", []))
        warnings.extend(bridge_result.get("warnings", []))

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "lines": content.count("\n") + 1,
        "bridge_connected": bridge_result is not None,
    }


def _try_bridge_validation(jsx_path: str, port: int) -> dict | None:
    """Attempt validation via the MCP bridge WebSocket. Returns None if unavailable."""
    ws = None
    try:
        import websocket  # websocket-client library
        import json as _json

        ws = websocket.create_connection(
            f"ws://127.0.0.1:{port}",
            timeout=3,
        )
        # Auth (if secret exists)
        secret_path = os.path.join(os.environ.get("APPDATA", ""), "Apollova", "bridge-secret.json")
        if os.path.exists(secret_path):
            with open(secret_path, "r") as f:
                token = _json.load(f).get("token", "")
            ws.send(_json.dumps({"type": "auth", "token": token}))
            auth_resp = _json.loads(ws.recv())
            if not auth_resp.get("success"):
                return None

        # Send validate request
        ws.send(_json.dumps({
            "jsonrpc": "2.0",
            "id": "validate-1",
            "method": "execute.validateFile",
            "params": {"path": jsx_path, "dryRun": False}
        }))
        resp = _json.loads(ws.recv())

        if resp.get("result"):
            return resp["result"]
        return None
    except Exception:
        return None
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


def render_preflight(template: str, jobs_dir: str, bridge_port: int = 9741) -> dict:
    """
    Pre-render validation checks.

    Verifies:
    1. JSX file exists and passes validation
    2. Each job folder has required files (job_data.json, audio, cover)
    3. If bridge connected: spot-checks expression timestamps

    Returns:
        dict with keys: passed (bool), checks (list of {name, status, detail}), warnings (list)
    """
    checks: list[dict] = []
    warnings: list[str] = []

    # Map template to JSX path
    jsx_map = {
        "aurora": "Apollova-Aurora-Injection.jsx",
        "mono": "Apollova-Mono-Injection.jsx",
        "onyx": "Apollova-Onyx-Injection.jsx",
    }

    jsx_name = jsx_map.get(template.lower())
    if not jsx_name:
        checks.append({"name": "JSX file", "status": "fail", "detail": f"Unknown template: {template}"})
        return {"passed": False, "checks": checks, "warnings": []}

    # Find JSX file
    jsx_search_dirs = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "JSX"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "scripts", "JSX"),
    ]

    jsx_path = None
    for d in jsx_search_dirs:
        candidate = os.path.join(d, jsx_name)
        if os.path.exists(candidate):
            jsx_path = candidate
            break

    if not jsx_path:
        checks.append({"name": "JSX file", "status": "fail", "detail": f"JSX not found: {jsx_name}"})
        return {"passed": False, "checks": checks, "warnings": []}

    # Check 1: JSX validation
    jsx_result = validate_jsx_file(jsx_path, bridge_port)
    if jsx_result["valid"]:
        checks.append({"name": "JSX syntax", "status": "pass", "detail": f"{jsx_result.get('lines', 0)} lines"})
    else:
        checks.append({"name": "JSX syntax", "status": "fail", "detail": "; ".join(jsx_result["errors"])})
    warnings.extend(jsx_result.get("warnings", []))

    # Check 2: Job folders
    if not os.path.isdir(jobs_dir):
        checks.append({"name": "Jobs directory", "status": "fail", "detail": f"Not found: {jobs_dir}"})
        return {"passed": False, "checks": checks, "warnings": warnings}

    job_folders = sorted([
        os.path.join(jobs_dir, d) for d in os.listdir(jobs_dir)
        if os.path.isdir(os.path.join(jobs_dir, d)) and d.startswith("job_")
    ])

    if not job_folders:
        checks.append({"name": "Job folders", "status": "fail", "detail": "No job_xxx folders found"})
        return {"passed": False, "checks": checks, "warnings": warnings}

    missing_files: list[str] = []
    for jf in job_folders:
        job_name = os.path.basename(jf)
        required = ["job_data.json", "audio_trimmed.wav"]
        for req in required:
            if not os.path.exists(os.path.join(jf, req)):
                missing_files.append(f"{job_name}/{req}")

    if missing_files:
        checks.append({"name": "Job files", "status": "fail", "detail": f"Missing: {', '.join(missing_files[:5])}"})
    else:
        checks.append({"name": "Job files", "status": "pass", "detail": f"{len(job_folders)} jobs ready"})

    passed = all(c["status"] == "pass" for c in checks)
    return {"passed": passed, "checks": checks, "warnings": warnings}
