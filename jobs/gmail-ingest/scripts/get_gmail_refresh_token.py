import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from gmail_ingest import GMAIL_SCOPES, REPO_ROOT  # noqa: E402


load_dotenv(dotenv_path=REPO_ROOT / ".env")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)


def main():
    client_config = {
        "installed": {
            "client_id": os.environ["GMAIL_CLIENT_ID"],
            "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, GMAIL_SCOPES)
    credentials = flow.run_local_server(
        port=0,
        prompt="consent",
        open_browser=False,
        timeout_seconds=300,
    )

    print("GMAIL_REFRESH_TOKEN=")
    print(credentials.refresh_token or "")


if __name__ == "__main__":
    main()
