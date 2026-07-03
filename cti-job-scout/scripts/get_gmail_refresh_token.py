"""One-time, local-only script to obtain a Gmail OAuth2 refresh token.

Prerequisites (see README "Gmail API setup" for the click-by-click version):
  1. A Google Cloud project with the Gmail API enabled.
  2. An OAuth client of type "Desktop app"; download its JSON as
     credentials.json next to this script (it is gitignored).

Run:
    pip install google-auth-oauthlib
    python scripts/get_gmail_refresh_token.py

A browser window opens; sign in with the Gmail account that should SEND the
digests and approve the gmail.send scope. The script then prints the three
values to store as GitHub secrets. Never commit credentials.json or the
printed values.
"""

import json
import sys
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"


def main() -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        sys.exit("Missing dependency. Run: pip install google-auth-oauthlib")

    if not CREDENTIALS_FILE.exists():
        sys.exit(
            f"Put your OAuth Desktop-app client JSON at {CREDENTIALS_FILE}\n"
            "(Google Cloud Console -> APIs & Services -> Credentials -> "
            "Create credentials -> OAuth client ID -> Desktop app -> Download JSON)"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    # access_type=offline + prompt=consent guarantees a refresh token is
    # issued even if you've authorized this client before.
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent"
    )

    client_config = json.loads(CREDENTIALS_FILE.read_text())["installed"]
    print("\nStore these as GitHub repo secrets (Settings -> Secrets -> Actions):\n")
    print(f"GMAIL_CLIENT_ID={client_config['client_id']}")
    print(f"GMAIL_CLIENT_SECRET={client_config['client_secret']}")
    print(f"GMAIL_REFRESH_TOKEN={creds.refresh_token}")
    print("\nAlso set DIGEST_RECIPIENT to the address that should receive digests.")


if __name__ == "__main__":
    main()
