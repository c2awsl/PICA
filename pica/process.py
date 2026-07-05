import logging
import os
import signal
import subprocess
import sys
import time

logger = logging.getLogger(__name__)


class ScannerProcess:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self._process: subprocess.Popen | None = None

    def start(self):
        if self._process is not None:
            logger.warning("scanner process already running")
            return
        args = [sys.executable, "-m", "pica.scanner_worker", self.config_path]
        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        logger.info("scanner process started (pid=%d)", self._process.pid)

    def stop(self, timeout: float = 5.0) -> bool:
        if self._process is None:
            return True
        logger.info("stopping scanner process (pid=%d)...", self._process.pid)
        self._process.terminate()
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("scanner process did not terminate in %.1fs, killing", timeout)
            self._process.kill()
            self._process.wait()
        self._process = None
        logger.info("scanner process stopped")
        return True

    @property
    def is_running(self) -> bool:
        if self._process is None:
            return False
        ret = self._process.poll()
        return ret is None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    def is_alive(self) -> bool:
        return self.is_running
