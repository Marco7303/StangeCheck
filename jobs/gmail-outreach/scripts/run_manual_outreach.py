import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from gmail_outreach import GmailOutreachProcessor, REPO_ROOT  # noqa: E402


load_dotenv(dotenv_path=REPO_ROOT / ".env")


def main():
    result = GmailOutreachProcessor().run()
    print(result)


if __name__ == "__main__":
    main()
