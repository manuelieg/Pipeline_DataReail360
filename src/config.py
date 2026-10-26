"""Configuración centralizada del proyecto."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _path_from_env(variable: str, default: Path) -> Path:
    candidate = Path(os.getenv(variable, str(default)))
    return candidate if candidate.is_absolute() else (BASE_DIR / candidate).resolve()


DATA_PATH = _path_from_env("DATA_PATH", BASE_DIR / "data" / "online_retail_muestra_2000.csv")

MAX_SOURCE_ROWS = max(0, int(os.getenv("MAX_SOURCE_ROWS", "2000")))
DB_PATH = _path_from_env("DB_PATH", BASE_DIR / "dataretail360.db")
SCHEMA_PATH = _path_from_env("SCHEMA_PATH", BASE_DIR / "db" / "schema.sql")
LOGS_DIR = _path_from_env("LOGS_DIR", BASE_DIR / "logs")
REPORTS_DIR = _path_from_env("REPORTS_DIR", BASE_DIR / "logs" / "reportes")
BATCH_SIZE = max(1, int(os.getenv("BATCH_SIZE", "1000")))

LOGS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
