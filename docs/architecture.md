# PICA 系统架构设计

## 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                     Tauri v2 Desktop Shell                │
│  ┌───────────────────────────────────────────────────┐  │
│  │              Rust 主进程 (lib.rs)                   │  │
│  │  • 启动 Python 子进程 (python -m pica web)        │  │
│  │  • 轮询 127.0.0.1:8765 等待服务就绪               │  │
│  │  • 窗口关闭时 kill Python 子进程                  │  │
│  │  • 管理 WebView 生命周期                          │  │
│  └──────────────────────┬────────────────────────────┘  │
│                         │ HTTP                           │
│  ┌──────────────────────▼────────────────────────────┐  │
│  │              WebView (webview/index.html)          │  │
│  │  • 加载 http://127.0.0.1:8765                     │  │
│  │  • 启动时显示 loading spinner                     │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│                   Python 后端 (pica/)                     │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │ Scanner  │  │ Watcher  │  │  FastAPI Web (uvicorn)│   │
│  │ (子进程)  │  │ (线程)   │  │  routes_*.py          │   │
│  │ 扫描文件  │  │ 监控新文件 │  │  templates/*.html     │   │
│  │ MD5去重   │  │ 入队Worker│  │  Alpine.js + htmx    │   │
│  └────┬─────┘  └────┬─────┘  └──────────────────────┘   │
│       │             │                                    │
│       └──────┬──────┘                                    │
│              ▼                                            │
│  ┌──────────────────┐  ┌──────────────────┐             │
│  │  Worker (协程队列) │  │ AiProcessor (线程) │             │
│  │  • 文件入队       │  │  • 轮询 pending   │             │
│  │  • MD5 + phash    │  │  • 调用 Ollama     │             │
│  │  • Recognizer识别  │  │  • 写入识别结果    │             │
│  │  • 复制到 pending  │  │  • 分组计算        │             │
│  └──────────────────┘  └──────────────────┘             │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │              数据库 (SQLAlchemy + SQLite)         │   │
│  │  Image, Category, Tag, ImageCategory, ImageTag,  │   │
│  │  SimilarGroup, AuditLog, StorageBox, ScanStatus   │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

## 模块职责

### `pica/__main__.py` — 应用入口

CLI 入口，支持 3 种运行模式：

| 子命令 | 启动内容 | 适用场景 |
|--------|---------|---------|
| `all`（默认） | Web + Scanner 子进程 + Watcher + AiProcessor | 完整功能，自动扫描 |
| `web` | Web + Watcher + AiProcessor | 手动控制扫描 |
| `scanner` | 仅运行扫描（独立进程） | 配合外部 Web 服务 |

启动流程：
1. 加载配置文件（`config.json` 或 `--config` 指定）
2. `init_db()` — 初始化数据库连接，执行 schema 迁移
3. 按模式启动对应组件
4. `uvicorn.run()` — 启动 FastAPI 服务器
5. 后台线程监控配置文件变更（每 3 秒），自动重载

### `pica/config.py` — 配置管理

- 基于 `dataclass` 的配置对象
- 从 `config.json` 读取，运行时可通过 Web 界面修改
- 自动补充派生路径（`sync_dir`, `archive_dir`, `pending_dir`, `thumbnails_dir`, `data_dir`）
- `ensure_dirs()` 确保所有必需目录存在
- `reload()` / `save()` 支持运行时配置重载和持久化
- `on_reload()` 注册变更回调（页面等使用）

### `pica/database.py` — 数据模型

**Image 表**（核心实体，30+ 字段）：
- 基础信息：filename, filepath, md5_hash, file_size, width, height
- 状态控制：status (pending/confirmed/rejected/recycled/skipped), ai_status (pending/processing/done/failed)
- AI 结果（JSON 字符串字段，向后兼容用）：suggested_category, suggested_tags
- 用户确认结果（JSON 字符串字段，向后兼容用）：confirmed_category, confirmed_tags
- 结构化字段：work_name, image_type, has_text, extracted_text
- 识别元数据：ai_model, ai_latency_ms, ai_at, confirmed_at, processed_at
- 分组：phash, similar_group_id
- 关联关系：category_links → ImageCategory, tag_links → ImageTag

**Category 表** — 层级分类树：
- id, parent_id（自引用外键）, name, sort_order
- 支持无限层级嵌套，AI 可以自由创建新分类

**Tag 表** — 统一标签库：
- id, name, color（可选）, usage_count
- 全局统一，可合并同义词、删除脏标签

**关联表**（SQLAlchemy ORM 关系）：
- ImageCategory: image_id, category_id, source (ai_suggested/confirmed)
- ImageTag: image_id, tag_id, source (ai_suggested/confirmed)

**其他表**：
- SimilarGroup: phash 近似分组
- AuditLog: 操作审计日志（image_id, action, old_value, new_value, source）
- StorageBox / StorageBoxItem: 收纳盒功能
- ScanStatus: 扫描状态控制

**ORM 关联**：
```python
Image.category_links → [ImageCategory] → Category
Image.tag_links → [ImageTag] → Tag
Image.similar_group → SimilarGroup
```

**数据迁移**：`_migrate_json_to_relations()` 在 `init_db()` 时自动运行，将旧的 JSON 字段（suggested_category, confirmed_category, suggested_tags, confirmed_tags）迁移到新的 Junction 表并标记 `source`。

### `pica/scanner.py` — 扫描核心

- 遍历 `scan_sources` 配置的所有目录（递归）
- 过滤扩展名（`allowed_extensions`）
- 计算 MD5 哈希检查是否已存在（去重）
- 复制新文件到 `pending/`（文件名 = `{md5_hash}{ext}`）
- 生成缩略图（`generate_thumbnail`）
- 记录 Image 记录到数据库

### `pica/scanner_worker.py` — 独立扫描进程

- 作为独立子进程运行（`python -m pica.scanner_worker config.json`）
- 持续循环扫描，通过 `ScanStatus` 表接收命令（idle/scan/exit）
- 被 `pica/process.py` 管理

### `pica/worker.py` — 异步任务队列

- `asyncio.Queue` + 信号量控制并发
- Watcher 发现新文件后入队
- 处理流程：MD5 → Ollama 识别 → 复制到 pending → 生成缩略图 → dhash → 记录数据库 → 分组
- 使用 `Recognizer.recognize()` 进行 AI 识别

### `pica/ai_processor.py` — 后台 AI 处理器（独立线程）

- 定时轮询数据库（每 2 秒），查找 `ai_status='pending'` 的图片
- 批量处理（每次最多 5 张）
- 处理流程与 Worker 的 AI 部分一致（Ollama 调用 → 保存结果 → 分组）
- 适用于图片已经通过其他方式入库（如手动复制）后需要 AI 识别的场景

### `pica/recognizer.py` — AI 识别逻辑

- 调用 Ollama API（`POST /api/generate`）
- 解析 AI 返回的 JSON，处理异常格式（`_first_str()` / `_ensure_list()`）
- `_get_source_folder()` — 从文件路径提取源目录的文件夹名，作为优先分类建议
- `save_result_to_db()` — 将 AI 识别结果写入 ImageCategory/ImageTag 关联表
- `_ensure_category()` / `_ensure_tag()` — 确保分类/标签存在（不存在则自动创建）
- AI Prompt 引导模型返回结构化 JSON：category, work, type, tags, has_text, extracted_text

### `pica/archiver.py` — 文件操作

- `copy_to_pending()` — 从源目录复制到 `pending/`
- `archive_image()` — 从 pending 复制到 `archive/{category}/`
- `cleanup_pending()` — 归档后删除 pending 中的临时文件

### `pica/watcher.py` — 文件系统监控

- 使用 `watchdog` 库监控 `sync_dir/`
- 发现新文件时通过回调入队到 Worker

### `pica/grouping.py` — 近似分组

- 基于 dhash（差异哈希）计算图片相似度
- `assign_similar_group()` — 将图片分配到已有近似组或创建新组

### `pica/web/` — FastAPI Web 应用

**路由模块**（每个 `routes_*.py` 对应一个页面）：

| 路由 | 对应页面 | 核心 API |
|------|---------|---------|
| `/pending` | 待办页 | 列表/筛选/批量确认/驳回/重试AI/编辑 |
| `/archive` | 归档页 | 浏览/搜索/筛选/批量编辑 |
| `/categories` | 分类管理 | 树状浏览/CRUD/重命名/移动 |
| `/tags` | 标签管理 | CRUD/合并/查看标签图片 |
| `/groups` | 分组管理 | 自动分组/手动分组/合并/拆分 |
| `/recycle` | 回收站 | 恢复/永久删除 |
| `/boxes` | 收纳盒 | 创建/拖拽/归档 |
| `/scan` | 扫描 | 手动触发扫描 |
| `/stats` | 统计 | 计数/分布 |
| `/audit` | 审计日志 | 操作日志查看 |
| `/settings` | 设置 | 配置修改/保存 |
| `/browse` | API | 文件系统浏览（目录选择器用） |
| `/thumbnail` | API | 缩略图生成/服务 |

**前端技术栈**：
- 模板引擎：Jinja2
- 前端框架：Alpine.js 3.14（轻量响应式）
- AJAX 增强：htmx 1.9（局部刷新）
- 样式：Apple 风格玻璃拟态（CSS 自定义属性）
- 图标：Font Awesome 6
- 选择机制：全局 Marquee（框选）+ 点击选中
- 图片浏览：Lightbox（灯箱预览）

## 数据流

### 完整流程

```
手机拍照 → Syncthing 同步 → sync_dir/
  → Watcher 检测到新文件
  → Worker 入队
    → 计算 MD5 + dhash + 图片尺寸
    → 调用 Ollama API 识别
    → 复制到 pending/{md5}.{ext}
    → 生成缩略图 thumbnails/{md5}_256.jpg
    → 记录数据库（Image + 分类/标签关联）
    → 分配到近似分组
  → Web UI 显示待办列表

用户操作：
  → 在待办页浏览 AI 识别结果
  → 确认（可修改分类/标签）→ archive/{category}/{md5}.{ext}
  → 驳回 → status = recycled（软删除，可恢复）
  → 编辑 → 更新数据库记录
```

### 设计决策

1. **复制而非移动**：原始文件从不被修改，所有操作都是复制或创建副本
2. **MD5 精确去重 + dhash 近似分组**：不同分层，MD5 确保系统内无完全相同的图片，dhash 将相似图片归组便于批量处理
3. **源文件夹作为分类**：AI 识别时自动将 `scan_sources` 中的父目录名作为优先分类建议
4. **JSON 字段 + Junction 表双写**：旧的 JSON 字段保留作为 fallback，新的 Junction 表（ImageCategory/ImageTag）是主要数据源
5. **回收站不删文件**：回收站操作只改变 `Image.status` 为 `recycled`，实际文件保留
6. **始终开启的选择模式**：点击选中和框选共存，没有"切换选择模式"的概念
7. **玻璃拟态设计系统**：CSS 自定义属性（design tokens）统一定义颜色/圆角/模糊/阴影，所有页面引用 `var(--color-*)` 而非硬编码值

## 数据库关系图

```
Category ──┐
            ├── ImageCategory ──┐
            │                   ├── Image ──── SimilarGroup
            │                   │
Tag ────────┼── ImageTag ───────┘
            │
AuditLog ───┘ (image_id 引用 Image)

StorageBox ─── StorageBoxItem ─── Image

ScanStatus (key-value 表，控制扫描进程)
```

## 测试覆盖

- `test_scanner.py` — 扫描流程、MD5 去重、文件过滤
- `test_database.py` — 数据库模型 CRUD、关联查询、迁移
- `test_recognizer.py` — AI 结果解析、异常格式处理
- `test_archiver.py` — 文件复制、清理逻辑
- `test_utils.py` — 工具函数（dhash、MD5、图片尺寸）
