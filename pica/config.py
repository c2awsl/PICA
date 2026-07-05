import json
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class Config:
    project_root: Path = Path(__file__).resolve().parent.parent

    sync_dir: Path = field(init=False)
    archive_dir: Path = field(init=False)
    pending_dir: Path = field(init=False)
    thumbnails_dir: Path = field(init=False)
    data_dir: Path = field(init=False)
    db_path: Path = field(init=False)

    ollama_url: str = "http://localhost:11434/api/generate"
    ai_model: str = "llava:7b"
    ai_timeout: int = 120

    host: str = "0.0.0.0"
    port: int = 8765

    thumbnail_size: tuple = (256, 256)
    thumbnail_quality: int = 85

    watcher_interval: float = 1.0

    worker_max_concurrent: int = 1

    allowed_extensions: set = field(default_factory=lambda: {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"})

    scan_sources: list = field(default_factory=list)

    categories: list = field(default_factory=lambda: ["人物", "风景", "食物", "宠物", "其他"])

    ai_prompt: str = (
        'You are an image classification assistant. '
        'Analyze the image and return JSON with fields:\n'
        '1. "category": array of 1-3 categories (e.g., "梗图", "表情包", "动漫", "游戏", '
        '"截图", "长截图", "AI生成", "艺术照", "人物", "风景", "动物", "建筑", "食物")\n'
        '2. "work": the specific work/series/game name this image belongs to, '
        'or empty string if not applicable (e.g., "原神", "崩坏：星穹铁道", "孤独摇滚", '
        '"新世纪福音战士", "奥特曼")\n'
        '3. "type": image type from ("meme", "emoji", "screenshot", "long_screenshot", '
        '"fanart", "official_art", "ai_generated", "photo", "scan", "text_screenshot")\n'
        '4. "tags": array of 5-10 descriptive Chinese tags\n'
        'Respond ONLY with valid JSON, no explanation.'
    )

    config_file: Path | None = field(default=None, init=False)

    _on_reload: list = field(default_factory=list, init=False)

    def __post_init__(self):
        self.sync_dir = self.project_root / "sync_dir"
        self.archive_dir = self.project_root / "archive"
        self.pending_dir = self.project_root / "pending"
        self.thumbnails_dir = self.project_root / "thumbnails"
        self.data_dir = self.project_root / "data"
        self.db_path = self.data_dir / "pica.db"

    def ensure_dirs(self):
        for d in [self.sync_dir, self.pending_dir, self.thumbnails_dir, self.data_dir]:
            d.mkdir(parents=True, exist_ok=True)
        for cat in self.categories:
            (self.archive_dir / cat).mkdir(parents=True, exist_ok=True)
        (self.archive_dir / "未分类").mkdir(parents=True, exist_ok=True)

    def on_reload(self, callback):
        self._on_reload.append(callback)

    def to_dict(self) -> dict:
        d = {
            "ollama_url": self.ollama_url,
            "ai_model": self.ai_model,
            "ai_timeout": self.ai_timeout,
            "host": self.host,
            "port": self.port,
            "thumbnail_size": list(self.thumbnail_size),
            "thumbnail_quality": self.thumbnail_quality,
            "watcher_interval": self.watcher_interval,
            "worker_max_concurrent": self.worker_max_concurrent,
            "allowed_extensions": sorted(self.allowed_extensions),
            "scan_sources": self.scan_sources,
            "categories": self.categories,
            "ai_prompt": self.ai_prompt,
        }
        return d

    def update_from_dict(self, data: dict):
        for k, v in data.items():
            if k == "allowed_extensions" and isinstance(v, list):
                v = set(v)
            if k == "thumbnail_size" and isinstance(v, list):
                v = tuple(v)
            if hasattr(self, k) and k not in ("config_file", "project_root",
                                               "sync_dir", "archive_dir",
                                               "pending_dir", "thumbnails_dir",
                                               "data_dir", "db_path"):
                setattr(self, k, v)

    def reload(self):
        if self.config_file and self.config_file.exists():
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
            self.update_from_dict(data)
            self.ensure_dirs()
            for cb in self._on_reload:
                try:
                    cb()
                except Exception:
                    logger.exception("on_reload callback failed")
            logger.info("config reloaded from %s", self.config_file)

    def save(self):
        if self.config_file is None:
            self.config_file = Path("config.json")
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for cb in self._on_reload:
            try:
                cb()
            except Exception:
                logger.exception("on_reload callback failed")
        logger.info("config saved to %s", self.config_file)

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        cfg = cls()
        p = Path(path) if path else Path("config.json")
        cfg.config_file = p
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            cfg.update_from_dict(data)
        cfg.__post_init__()
        return cfg
