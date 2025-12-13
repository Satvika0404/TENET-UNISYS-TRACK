import sqlite3
from pathlib import Path

from app.core.config import settings


def main():
    sql_path = Path("scripts/migrate_attempts.sql")
    if not sql_path.exists():
        raise SystemExit(f"Missing SQL file: {sql_path.resolve()}")

    sql = sql_path.read_text(encoding="utf-8")

    con = sqlite3.connect(settings.db_path)
    try:
        con.executescript(sql)
        con.commit()
    finally:
        con.close()

    print("✅ Migration OK")
    print("DB:", settings.db_path)


if __name__ == "__main__":
    main()
