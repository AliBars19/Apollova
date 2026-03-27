"""
Apollova Secrets — HMAC key for offline license verification.

Setup:
  1. Copy this file to apollova_secrets.py (same directory)
  2. Replace the placeholder with your actual HMAC hex key
  3. NEVER commit apollova_secrets.py — it is gitignored

The key is used by apollova_license.py to verify license signatures
without hitting the server (offline mode).
"""

# Replace with your real 64-char hex HMAC key
HMAC_SECRET = "0000000000000000000000000000000000000000000000000000000000000000"
