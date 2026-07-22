from pathlib import Path

from alembic.config import Config

from alembic import command
from core.config import DATABASE_URL


def run_migrations() -> None:
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(cfg, "head")
