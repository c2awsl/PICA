import base64
import json
import time
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from pica.config import Config
from pica.database import Category, ImageCategory, ImageTag, Tag


class Recognizer:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _ensure_category(self, name: str, session: Session) -> Category:
        cat = session.query(Category).filter_by(name=name).first()
        if not cat:
            cat = Category(name=name)
            session.add(cat)
            session.flush()
        return cat

    def _ensure_tag(self, name: str, session: Session) -> Tag:
        tag = session.query(Tag).filter_by(name=name).first()
        if not tag:
            tag = Tag(name=name)
            session.add(tag)
            session.flush()
        return tag

    def save_result_to_db(self, image_id: int, result: dict, session: Session):
        """Write AI recognition result to the category/tag junction tables."""
        # Ensure the old JSON fields are also set for backward compat
        from pica.database import Image as ImageModel
        img = session.query(ImageModel).filter_by(id=image_id).first()
        if not img:
            return

        # Clear old links for this source
        session.query(ImageCategory).filter_by(image_id=image_id, source="suggested").delete()
        session.query(ImageTag).filter_by(image_id=image_id, source="suggested").delete()

        # Write categories
        for name in result.get("category", []):
            if name and isinstance(name, str):
                cat = self._ensure_category(name.strip(), session)
                session.add(ImageCategory(image_id=image_id, category_id=cat.id, source="suggested"))

        # Write tags
        for name in result.get("tags", []):
            if name and isinstance(name, str):
                tag = self._ensure_tag(name.strip(), session)
                session.add(ImageTag(image_id=image_id, tag_id=tag.id, source="suggested"))

        # Text detection
        img.has_text = 1 if result.get("has_text") else 0
        if result.get("extracted_text"):
            img.extracted_text = str(result.get("extracted_text"))

        # Also update old JSON fields for backward compat
        img.suggested_category = json.dumps(result.get("category", []), ensure_ascii=False)
        img.suggested_tags = json.dumps(result.get("tags", []), ensure_ascii=False)

        session.flush()

    async def recognize(self, image_path: str | Path) -> dict | None:
        image_path = str(image_path)
        try:
            b64 = self._encode_image(image_path)
        except (FileNotFoundError, PermissionError):
            return None

        payload = {
            "model": self.cfg.ai_model,
            "prompt": self.cfg.ai_prompt,
            "images": [b64],
            "stream": False,
            "format": "json",
        }
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.cfg.ai_timeout) as client:
                resp = await client.post(self.cfg.ollama_url, json=payload)
                resp.raise_for_status()
                result = resp.json()
                latency = (time.monotonic() - start) * 1000
                response_text = result.get("response", "{}")
                parsed = json.loads(response_text)

                def _first_str(v):
                    if isinstance(v, list):
                        return str(v[0]).strip() if v else ""
                    return str(v).strip() if v else ""

                def _ensure_list(v):
                    if isinstance(v, list):
                        return [str(x).strip() for x in v if x]
                    if isinstance(v, str):
                        return [x.strip() for x in v.split(",") if x.strip()]
                    return []

                return {
                    "category": _ensure_list(parsed.get("category", [])),
                    "tags": _ensure_list(parsed.get("tags", [])),
                    "work": _first_str(parsed.get("work", "")),
                    "image_type": _first_str(parsed.get("type", "")),
                    "has_text": bool(parsed.get("has_text", False)),
                    "extracted_text": _first_str(parsed.get("extracted_text", "")),
                    "model": self.cfg.ai_model,
                    "latency_ms": round(latency, 1),
                }
        except httpx.RequestError as e:
            return None
        except json.JSONDecodeError:
            return None
        except Exception:
            return None
