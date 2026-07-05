import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from pica.config import Config
from pica.database import Image, ImageStatus, SimilarGroup, get_session_factory, get_engine
from pica.recognizer import Recognizer
from pica.thumbnail import generate_thumbnail
from pica.archiver import copy_to_pending, archive_image, cleanup_pending
from pica.utils import md5_hash, dhash, get_image_size
from pica.grouping import assign_similar_group

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._queue = asyncio.Queue()
        self._recognizer = Recognizer(cfg)
        self._engine = get_engine(cfg)
        self._session_factory = get_session_factory(self._engine)
        self._running = False
        self._semaphore = asyncio.Semaphore(cfg.worker_max_concurrent)

    async def enqueue(self, filepath: str):
        await self._queue.put(filepath)

    async def start(self):
        self._running = True
        asyncio.create_task(self._process_loop())

    async def stop(self):
        self._running = False

    async def _process_loop(self):
        while self._running:
            try:
                filepath = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                async with self._semaphore:
                    await self._process_one(filepath)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.exception("worker error")

    async def _process_one(self, filepath: str):
        path = Path(filepath)
        if not path.exists():
            return

        file_hash = md5_hash(filepath)
        if not file_hash:
            return

        session = self._session_factory()
        try:
            existing = session.execute(
                select(Image).where(Image.md5_hash == file_hash)
            ).scalar_one_or_none()
            if existing is not None:
                return

            width, height = get_image_size(filepath)

            result = await self._recognizer.recognize(filepath)

            pending_path = copy_to_pending(filepath, file_hash, self.cfg)
            if not pending_path:
                return

            generate_thumbnail(pending_path, file_hash, self.cfg)

            ph = dhash(filepath)

            img = Image(
                filename=path.name,
                filepath=str(path),
                md5_hash=file_hash,
                file_size=path.stat().st_size,
                width=width,
                height=height,
                status=ImageStatus.PENDING,
                pending_path=str(pending_path),
                phash=ph,
            )

            session.add(img)
            session.flush()

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
            else:
                img.ai_status = "failed"
            assign_similar_group(session, img)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.exception("failed to process %s", filepath)
        finally:
            session.close()
