"""Initialize the database and create all tables."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pica.config import Config
from pica.database import init_db


def main():
    cfg = Config.load()
    engine = init_db(cfg)
    print(f"Database initialized at: {cfg.db_path}")
    print(f"Tables: {list(engine.table_names())}")


if __name__ == "__main__":
    main()
