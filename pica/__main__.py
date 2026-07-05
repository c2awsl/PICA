import argparse
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

import uvicorn

from pica.config import Config
from pica.database import init_db
from pica.watcher import FileWatcher
from pica.worker import Worker
from pica.scanner import run_scan_in_thread
from pica.web.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pica")


def watch_config_file(cfg: Config):
    if not cfg.config_file:
        return
    last_mtime = cfg.config_file.stat().st_mtime if cfg.config_file.exists() else 0
    while True:
        time.sleep(3)
        try:
            if cfg.config_file.exists():
                mtime = cfg.config_file.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    cfg.reload()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="PICA - Personal Image Classification Agent")
    parser.add_argument("--reload", action="store_true", help="enable auto-reload on file changes")
    parser.add_argument("--config", type=str, default=None, help="path to config.json")
    args = parser.parse_args()

    cfg_path = Path(args.config) if args.config else (Path("config.json") if Path("config.json").exists() else None)
    cfg = Config.load(cfg_path)
    cfg.ensure_dirs()

    engine = init_db(cfg)
    logger.info("database initialized at %s", cfg.db_path)

    worker = Worker(cfg)

    async def on_new_file(filepath: str):
        await worker.enqueue(filepath)

    watcher = FileWatcher(cfg, on_new_file)

    cfg_origin = cfg.config_file or Path("config.json")
    app = create_app(cfg, worker=worker, cfg_file_path=cfg_origin)

    reload_thread = threading.Thread(target=watch_config_file, args=(cfg,), daemon=True)
    reload_thread.start()

    watcher.start()
    logger.info("file watcher started on %s", cfg.sync_dir)

    if cfg.scan_sources:
        logger.info("starting initial scan of %d source(s)", len(cfg.scan_sources))
        run_scan_in_thread(cfg)

    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    try:
        uvicorn.run(
            app,
            host=cfg.host,
            port=cfg.port,
            log_level="info",
            reload=args.reload,
            reload_dirs=[str(cfg.project_root)] if args.reload else None,
            reload_includes=["*.py", "*.html", "config.json"] if args.reload else None,
        )
    finally:
        watcher.stop()
        logger.info("shutdown complete")


if __name__ == "__main__":
    main()
