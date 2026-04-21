"""
One-time Gmail OAuth setup.

Run this once to authorize the tracker to send email from your Gmail account.
It will open a browser, ask you to sign in, then write the credentials to .env.

Requirements (install once):
    pip install google-auth-oauthlib

Steps before running:
  1. Go to console.cloud.google.com and create a project (or pick an existing one).
  2. Enable the Gmail API:  APIs & Services → Enable APIs → search "Gmail API" → Enable.
  3. Create OAuth credentials:
       APIs & Services → Credentials → Create Credentials → OAuth client ID
       Application type: Desktop app  →  Create
  4. Download the JSON file and note the Client ID and Client Secret shown on screen
     (or open the downloaded JSON — they are under "installed.client_id" and
     "installed.client_secret").
  5. Paste those values when prompted below, then follow the browser flow.

After this script runs, your .env will contain GMAIL_REFRESH_TOKEN and you won't
need google-auth-oauthlib again.
"""

import os
import sys
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Missing dependency. Install it with:")
    print("    pip install google-auth-oauthlib")
    sys.exit(1)

_SCOPES   = ["https://www.googleapis.com/auth/gmail.send"]
_ENV_FILE = Path(__file__).parent / ".env"

_CLIENT_ID     = os.getenv("GMAIL_CLIENT_ID", "").strip()
_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "").strip()


def _prompt(label: str, current: str) -> str:
    if current:
        print(f"  {label} already set in .env — press Enter to keep, or paste a new value.")
        val = input(f"  {label}: ").strip()
        return val or current
    val = input(f"  {label}: ").strip()
    if not val:
        print(f"  ERROR: {label} is required.")
        sys.exit(1)
    return val


def _update_env(key: str, value: str) -> None:
    """Insert or replace a KEY=value line in .env."""
    lines = _ENV_FILE.read_text(encoding="utf-8").splitlines() if _ENV_FILE.exists() else []
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            lines[i] = f"{key}={value}"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}")
    _ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    print("=== Autospy — Gmail OAuth Setup ===\n")
    print("Paste your OAuth Client ID and Secret from Google Cloud Console.")
    print("(APIs & Services → Credentials → your Desktop app client)\n")

    client_id     = _prompt("GMAIL_CLIENT_ID",     _CLIENT_ID)
    client_secret = _prompt("GMAIL_CLIENT_SECRET", _CLIENT_SECRET)

    sender = os.getenv("GMAIL_SENDER", "").strip()
    if not sender:
        sender = input("\n  Your Gmail address (GMAIL_SENDER): ").strip()
        if not sender:
            print("  ERROR: Gmail address is required.")
            sys.exit(1)

    client_config = {
        "installed": {
            "client_id":                  client_id,
            "client_secret":              client_secret,
            "redirect_uris":              ["http://localhost"],
            "auth_uri":                   "https://accounts.google.com/o/oauth2/auth",
            "token_uri":                  "https://oauth2.googleapis.com/token",
        }
    }

    print("\nOpening your browser to authorize access...")
    print("Sign in with the Gmail account you want to send from.\n")

    flow = InstalledAppFlow.from_client_config(client_config, scopes=_SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    refresh_token = creds.refresh_token
    if not refresh_token:
        print("\nERROR: No refresh token returned. Try revoking access at")
        print("  myaccount.google.com/permissions  and re-running this script.")
        sys.exit(1)

    _update_env("GMAIL_CLIENT_ID",     client_id)
    _update_env("GMAIL_CLIENT_SECRET", client_secret)
    _update_env("GMAIL_REFRESH_TOKEN", refresh_token)
    _update_env("GMAIL_SENDER",        sender)

    print("\n=== Success ===")
    print(f"Credentials saved to {_ENV_FILE}")
    print("You can now run the tracker normally — emails will be sent via Gmail.")


if __name__ == "__main__":
    main()
