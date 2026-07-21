import os

from dotenv import load_dotenv

load_dotenv()

RAPT_USERNAME = os.getenv("RAPT_USERNAME", "")
RAPT_SECRET = os.getenv("RAPT_SECRET", "")
# single source of truth: project ../data/rapt.db (same folder the container bind-mounts)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///../data/rapt.db")
SYNC_INTERVAL_SECONDS = int(os.getenv("SYNC_INTERVAL_SECONDS", "60"))

TOKEN_URL = "https://id.rapt.io/connect/token"
API_BASE = "https://api.rapt.io"
