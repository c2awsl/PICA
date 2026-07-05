import asyncio
import json
import logging
import threading
import time
from datetime import datetime

from sqlalchemy import select

from pica.config import Config
from pica.database import Image, ImageStatus, get_engine, get_session_factory
from pica.recognizer import Recognizer
from pica.grouping import assign_similar_group

logger = logging.getLogger(__name__)

POLL_INTERVAL = 2.0
BATCH_LIMIT = 5


class AiProcessor:
    """Background thread that picks up images with ai_status='pending'
    and runs AI recognition on them."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._recognizer = Recognizer(cfg)
        self._engine = get_engine(cfg)
        self._session_factory = get_session_factory(self._engine)
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ai-processor")
        self._thread.start()
        logger.info("AI processor started")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._process_pending()
            except Exception:
                logger.exception("AI processor error")
            time.sleep(POLL_INTERVAL)

    def _process_pending(self):
        session = self._session_factory()
        try:
            images = session.execute(
                select(Image)
                .where(Image.status == ImageStatus.PENDING)
                .where(Image.ai_status == "pending")
                .limit(BATCH_LIMIT)
            ).scalars().all()

            for img in images:
                if not self._running:
                    break
                if not img.pending_path:
                    img.ai_status = "failed"
                    session.commit()
                    continue

                img.ai_status = "processing"
                session.commit()

                try:
                    result = asyncio.run(self._recognizer.recognize(img.pending_path))
                    if result:
                        self._recognizer.save_result_to_db(img.id, result, session)
                        img.suggested_category = json.dumps(result.get("category", []), ensure_ascii=False)
                        img.suggested_tags = json.dumps(result.get("tags", []), ensure_ascii=False)
                        img.work_name = result.get("work", "")
                        img.image_type = result.get("image_type", "")
                        img.ai_model = result.get("model")
                        img.ai_latency_ms = result.get("latency_ms")
                        img.ai_at = datetime.utcnow()
                        img.ai_status = "done"
                        assign_similar_group(session, img)
                    else:
                        img.ai_status = "failed"
                except Exception:
                    img.ai_status = "failed"
                    logger.exception("AI recognition failed for image %d", img.id)

                session.commit()

        except Exception:
            session.rollback()
            logger.exception("AI processor batch error")
        finally:
            session.close()
