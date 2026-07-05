import argparse
import atexit
import logging
import signal
import sys
import threading
import time
from pathlib import Path

import uvicorn

from pica.config import Config
from pica.database import ScanStatus, get_engine, get_session_factory, init_db
from pica.process import ScannerProcess
from pica.watcher import FileWatcher
from pica.worker import Worker
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


def send_db_command(cfg: Config, cmd: str):
    engine = get_engine(cfg)
    sf = get_session_factory(engine)
    session = sf()
    try:
        row = session.get(ScanStatus, "command")
        if row:
            row.value = cmd
        else:
            session.add(ScanStatus(key="command", value=cmd))
        session.commit()
    finally:
        session.close()


def run_web(args):
    cfg = load_config(args.config)
    engine = init_db(cfg)

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
        logger.info("web shutdown complete")


def run_scanner(args):
    cfg = load_config(args.config)
    cfg.ensure_dirs()
    engine = init_db(cfg)

    send_db_command(cfg, "idle")

    from pica.scanner_worker import scan_loop
    scan_loop(cfg)


def run_all(args):
    cfg = load_config(args.config)
    engine = init_db(cfg)

    scanner_proc = ScannerProcess(str(cfg.config_file or "config.json"))
    scanner_proc.start()

    def cleanup():
        logger.info("shutting down scanner process...")
        send_db_command(cfg, "exit")
        scanner_proc.stop(timeout=3.0)

    atexit.register(cleanup)

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
        cleanup()
        logger.info("all shutdown complete")


def load_config(config_arg: str | None) -> Config:
    cfg_path = Path(config_arg) if config_arg else Path("config.json")
    cfg = Config.load(cfg_path)
    cfg.ensure_dirs()
    return cfg


def main():
    parser = argparse.ArgumentParser(description="PICA - Personal Image Classification Agent")
    parser.add_argument("--config", type=str, default=None, help="path to config.json")
    parser.add_argument("--reload", action="store_true", help="enable auto-reload on file changes (web only)")
    parser.add_argument("subcommand", nargs="?", default="all", choices=["web", "scanner", "all"],
                        help="web/scanner/all (default: all)")

    args = parser.parse_args()

    if args.subcommand == "web":
        run_web(args)
    elif args.subcommand == "scanner":
        run_scanner(args)
    else:
        run_all(args)


if __name__ == "__main__":
    main()
