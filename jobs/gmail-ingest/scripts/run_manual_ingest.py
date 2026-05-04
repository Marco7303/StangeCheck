import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from gmail_ingest import GmailBeerPriceProcessor, REPO_ROOT  # noqa: E402


load_dotenv(dotenv_path=REPO_ROOT / ".env")


def main():
    result = GmailBeerPriceProcessor().process_inbox()
    print(result)


if __name__ == "__main__":
    main()
