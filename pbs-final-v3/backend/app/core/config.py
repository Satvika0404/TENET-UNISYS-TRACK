from pydantic import BaseModel
from dotenv import load_dotenv
import os
import yaml
from pathlib import Path

load_dotenv()

class Settings(BaseModel):
    cors_allow_origins: list[str] = ["http://localhost:8501", "http://127.0.0.1:8501"]
    db_path: str = os.getenv("PBS_DB_PATH", str(Path(__file__).resolve().parents[3] / "pbs.sqlite3"))
    config_path: str = os.getenv("PBS_CONFIG_PATH", str(Path(__file__).resolve().parents[3] / "config.yaml"))

settings = Settings()

def load_yaml_config() -> dict:
    path = Path(settings.config_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
