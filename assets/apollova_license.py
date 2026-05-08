import os
import sys
import re
import hashlib
import hmac as _hmac
import subprocess
import datetime
from pathlib import Path

import json as _json
import urllib.request
import urllib.error

# Secret is loaded from apollova_secrets.py (gitignored, bundled by PyInstaller).
# See apollova_secrets.example.py for setup instructions.
from apollova_secrets import HMAC_SECRET as _HMAC_SECRET_HEX
_HMAC_SECRET = bytes.fromhex(_HMAC_SECRET_HEX)

API_BASE = "https://apollova.co.uk/api"
ENV_FILE = Path(os.environ.get("APPDATA", "")) / "Apollova" / "apollova.env"
VERIFY_INTERVAL_HOURS = 24

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# ─────────────────────────────────────────────────────────────────────────────
# Hardware fingerprinting
# ─────────────────────────────────────────────────────────────────────────────

def get_hardware_fingerprint() -> str:
    """
    Return SHA256(motherboard_UUID | USERNAME | COMPUTERNAME).

    Uses the exact same data sources and hash as Activator.jsx (certutil SHA256),
    so the fingerprint is identical on both sides.
    """
    parts = []

    # 1. Motherboard UUID — most stable, tied to hardware
    try:
        r = subprocess.run(
            ["wmic", "csproduct", "get", "uuid"],
            capture_output=True, text=True, timeout=5,
            creationflags=_NO_WINDOW,
        )
        lines = [ln.strip() for ln in r.stdout.strip().splitlines()]
        # Line 0 = "UUID" header, line 1 = actual UUID value
        if len(lines) >= 2 and lines[1] and lines[1].lower() != "uuid":
            parts.append(lines[1])
    except Exception:
        pass

    # 2. Windows username
    parts.append(os.environ.get("USERNAME", "unknown"))

    # 3. Machine hostname
    parts.append(os.environ.get("COMPUTERNAME", "unknown"))

    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# .env file read / write
# ─────────────────────────────────────────────────────────────────────────────

def _load_env() -> dict | None:
    """Parse apollova.env. Returns None if missing or missing required fields."""
    if not ENV_FILE.exists():
        return None
    data: dict[str, str] = {}
    try:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                data[k.strip()] = v.strip()
    except Exception:
        return None
    required = {"APOLLOVA_LICENSE_KEY", "APOLLOVA_HW_FINGERPRINT",
                "APOLLOVA_LAST_VERIFIED", "APOLLOVA_TOKEN"}
    return data if required.issubset(data) else None


def _save_env(license_key: str, hw_fingerprint: str, token: str) -> None:
    """Write all four license fields to apollova.env (creates dir if needed)."""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat()
    ENV_FILE.write_text(
        f"APOLLOVA_LICENSE_KEY={license_key}\n"
        f"APOLLOVA_HW_FINGERPRINT={hw_fingerprint}\n"
        f"APOLLOVA_LAST_VERIFIED={now}\n"
        f"APOLLOVA_TOKEN={token}\n",
        encoding="utf-8",
    )


def _refresh_verified(env: dict, new_token: str) -> None:
    """Update LAST_VERIFIED (and optionally TOKEN) after a successful server call."""
    _save_env(
        env["APOLLOVA_LICENSE_KEY"],
        env["APOLLOVA_HW_FINGERPRINT"],
        new_token if new_token else env["APOLLOVA_TOKEN"],
    )


def delete_license() -> None:
    """Remove the stored license file (called on revocation or .env tampering)."""
    try:
        ENV_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# HMAC token helpers
# ─────────────────────────────────────────────────────────────────────────────

def _compute_token(license_key: str, hw_fingerprint: str) -> str:
    return _hmac.new(
        _HMAC_SECRET,
        f"{license_key}:{hw_fingerprint}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _verify_token_local(token: str, license_key: str, hw_fingerprint: str) -> bool:
    expected = _compute_token(license_key, hw_fingerprint)
    return _hmac.compare_digest(token, expected)


def _needs_server_verify(env: dict) -> bool:
    try:
        last = datetime.datetime.fromisoformat(env["APOLLOVA_LAST_VERIFIED"])
        age_h = (datetime.datetime.utcnow() - last).total_seconds() / 3600
        return age_h >= VERIFY_INTERVAL_HOURS
    except Exception:
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Server calls
# ─────────────────────────────────────────────────────────────────────────────

def _post(endpoint: str, payload: dict) -> tuple[int, dict]:
    data = _json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/{endpoint}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            try:
                body = _json.loads(resp.read().decode("utf-8"))
            except Exception:
                body = {}
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = _json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {}
        return e.code, body


def _server_verify(license_key: str, hw_fingerprint: str) -> tuple[bool, str, str]:
    """
    Call /api/verify. Returns (ok, message, new_token).
    Network errors are treated as offline grace — returns (True, "offline", "").
    """
    try:
        status, body = _post("verify", {
            "licenseKey": license_key,
            "hwFingerprint": hw_fingerprint,
        })
    except (urllib.error.URLError, OSError, TimeoutError):
        return True, "offline", ""
    except Exception:
        return True, "offline", ""

    if status == 200 and body.get("valid"):
        return True, "ok", body.get("token", "")

    return False, body.get("error", "License verification failed."), ""


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def check_license() -> tuple[bool, str]:
    """
    Full startup license check. Returns (valid, reason).

    Failure reasons:
      "no_license"        — no .env file found (first-time user)
      "hardware_mismatch" — .env copied from a different machine
      "invalid_token"     — .env tampered with, or a fake server wrote it
      "revoked"           — server explicitly revoked this license
      "<error message>"   — other server rejection
    """
    current_fp = get_hardware_fingerprint()
    env = _load_env()

    if env is None:
        return False, "no_license"

    # 1. Hardware binding check (local, instant)
    if env["APOLLOVA_HW_FINGERPRINT"] != current_fp:
        delete_license()
        return False, "hardware_mismatch"

    # 2. HMAC token check (local, prevents MITM / fake server responses)
    if not _verify_token_local(env["APOLLOVA_TOKEN"], env["APOLLOVA_LICENSE_KEY"], current_fp):
        delete_license()
        return False, "invalid_token"

    # 3. Periodic server re-verification (every 24h)
    if _needs_server_verify(env):
        ok, msg, new_token = _server_verify(env["APOLLOVA_LICENSE_KEY"], current_fp)
        if not ok:
            delete_license()
            return False, msg
        _refresh_verified(env, new_token)

    return True, "ok"


def activate_license(license_key: str) -> tuple[bool, str]:
    """
    Activate a new license key. Calls /api/activate and saves the .env on success.
    Returns (success, message).
    """
    license_key = license_key.strip().upper()

    if not re.fullmatch(r"[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}", license_key):
        return False, "Invalid format. Expected: XXXX-XXXX-XXXX-XXXX"

    hw_fingerprint = get_hardware_fingerprint()

    try:
        status, body = _post("activate", {
            "licenseKey": license_key,
            "hwFingerprint": hw_fingerprint,
        })
    except (urllib.error.URLError, OSError, TimeoutError):
        return False, (
            "Cannot connect to the activation server.\n"
            "Please check your internet connection and try again."
        )
    except Exception as e:
        return False, f"Unexpected error: {e}"

    if status == 200 and body.get("success"):
        token = body.get("token", "")
        if not token:
            return False, "Server returned an invalid response.\nPlease contact support@apollova.co.uk"
        _save_env(license_key, hw_fingerprint, token)
        return True, body.get("message", "License activated successfully!")

    err = body.get("error", "")
    if status == 404:
        return False, "License key not found.\nPlease double-check your key and try again."
    if status == 403:
        if "revoked" in err.lower():
            return False, "This license has been revoked.\nPlease contact support@apollova.co.uk"
        if "another" in err.lower() or "hardware" in err.lower():
            return False, (
                "This license is already activated on another computer.\n\n"
                "If you recently upgraded your PC, contact support@apollova.co.uk\n"
                "to reset your license binding."
            )
    return False, err or f"Activation failed (HTTP {status}). Please try again."
