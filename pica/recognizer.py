import json
import time
from pathlib import Path

import httpx

from pica.config import Config


class Recognizer:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    async def recognize(self, image_path: str | Path) -> dict | None:
        image_path = str(image_path)
        payload = {
            "model": self.cfg.ai_model,
            "prompt": self.cfg.ai_prompt,
            "images": [image_path],
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
                return {
                    "category": parsed.get("category", []),
                    "tags": parsed.get("tags", []),
                    "model": self.cfg.ai_model,
                    "latency_ms": round(latency, 1),
                }
        except httpx.RequestError as e:
            return None
        except json.JSONDecodeError:
            return None
        except Exception:
            return None
