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
2. `init_db()` — 初始化数据库连接，执行 schema 迁移（含 JSON→Junction 表迁移）
3. 按模式启动对应组件
4. `uvicorn.run()` — 启动 FastAPI 服务器
5. 后台线程监控配置文件变更（每 3 秒），自动重载

**命令行参数**：

```
usage: python -m pica [--config PATH] [--reload] [web|scanner|all]
```

- `--config`：指定配置文件路径，默认 `config.json`
- `--reload`：文件变更自动重载（开发用），仅 web/all 模式有效
- `subcommand`：运行模式（web/scanner/all），默认 all

### `pica/config.py` — 配置管理

- 基于 `dataclass` 的配置对象
- 从 `config.json` 读取，运行时可通过 Web 界面修改
- 自动补充派生路径（`sync_dir`, `archive_dir`, `pending_dir`, `thumbnails_dir`, `data_dir`）
- `ensure_dirs()` 确保所有必需目录存在
- `reload()` / `save()` 支持运行时配置重载和持久化
- `on_reload()` 注册变更回调

**配置热重载**：`watch_config_file()` 在后台线程每 3 秒检查文件 mtime，变化时自动 `cfg.reload()`。

### `pica/database.py` — 数据模型

**Image 表**（核心实体，30+ 字段）：

| 字段分组 | 字段 | 说明 |
|---------|------|------|
| 基础信息 | `filename`, `filepath`, `md5_hash`, `file_size`, `width`, `height` | 文件元数据 |
| 状态控制 | `status` (pending/confirmed/rejected/recycled/skipped), `ai_status` (pending/processing/done/failed) | 生命周期 |
| AI 结果（JSON 向后兼容） | `suggested_category`, `suggested_tags` | AI 原始输出 |
| 用户确认（JSON 向后兼容） | `confirmed_category`, `confirmed_tags` | 用户确认值 |
| 结构化字段 | `work_name`, `image_type`, `has_text`, `extracted_text` | 直接查询用 |
| 识别元数据 | `ai_model`, `ai_latency_ms`, `ai_at`, `confirmed_at`, `processed_at` | 时间与模型溯源 |
| 分组 | `phash`, `similar_group_id` | 近似重复检测 |
| 标记 | `user_edited` | 用户是否手动修改过 |

**Category 表** — 层级分类树：
- `id`, `parent_id`（自引用外键）, `name`, `sort_order`, `color`
- 支持无限层级嵌套，AI 或用户可以自由创建新分类
- UI：左侧树状导航，点击展开/折叠

**Tag 表** — 统一标签库：
- `id`, `name`, `color`, `usage_count`
- 全局统一，无重复，可合并同义词、删除脏标签

**关联表**（新版数据源，旧 JSON 字段为 fallback）：

| 表 | 字段 | 说明 |
|---|------|------|
| `ImageCategory` | image_id, category_id, source (ai_suggested/confirmed) | 多对多，source 区分 AI 建议还是用户确认 |
| `ImageTag` | image_id, tag_id, source (ai_suggested/confirmed) | 同上 |

**其他表**：

| 表 | 说明 |
|---|------|
| `SimilarGroup` | phash 近似分组（name, phash_ref, processed） |
| `AuditLog` | 审计日志（image_id, action, old_value, new_value, source, created_at） |
| `StorageBox` | 收纳盒（name, color, created_at） |
| `StorageBoxItem` | 收纳盒条目（box_id, image_id, added_at） |
| `ScanStatus` | 扫描状态控制（key-value，用命令模式控制子进程） |

**数据迁移策略**：
- `_migrate_json_to_relations()` 在 `init_db()` 时自动运行
- 将旧 JSON 字段（suggested_category, confirmed_category 等）解析后写入 Junction 表
- 已迁移的记录跳过（幂等设计）
- `to_dict()` 优先从 Junction 表读取，JSON 字段做 fallback

### `pica/scanner.py` — 扫描核心

流程：
1. 遍历 `scan_sources` 配置的所有目录（`rglob("*")` 递归）
2. 过滤扩展名（`allowed_extensions`）
3. 计算 MD5 哈希 → 查询数据库去重
4. 复制新文件到 `pending/{md5_hash}{ext}`
5. 生成缩略图 `thumbnails/{md5_hash}_256.jpg`
6. 记录 Image 记录到数据库

**去重策略**：基于 MD5 哈希精确去重，同文件内容不会被重复入库。phash 近似分组是后续 AI 处理阶段的事。

### `pica/scanner_worker.py` — 独立扫描进程

- 作为独立子进程运行（`python -m pica.scanner_worker config.json`）
- 通过 `ScanStatus` 表接收命令：`idle`（空闲）, `scan`（开始扫描）, `exit`（退出）
- 扫描循环：执行 `scan_sources()` → 完成后设置回 `idle` → 等待 5 秒后重试
- 被 `pica/process.py` 管理（`ScannerProcess` 类封装子进程生命周期）

### `pica/worker.py` — 异步任务队列

- Watcher 发现新文件后 `enqueue()` 入队
- `asyncio.Queue` + 信号量（`worker_max_concurrent`）控制并发
- 处理流程：MD5 → Ollama 识别 → 复制到 pending → 生成缩略图 → dhash → 记录数据库 → 分组

### `pica/ai_processor.py` — 后台 AI 处理器（独立线程）

- 定时轮询数据库（每 2 秒），查找 `ai_status='pending'` 的图片
- 批量处理（每次最多 5 张）
- 处理流程与 Worker 的 AI 部分一致
- 与 Worker 的区别：Worker 处理 Watcher 新入队的文件（含 copy + thumb），AiProcessor 处理已入库但未 AI 识别的图片（如手动复制到 pending/）

### `pica/recognizer.py` — AI 识别逻辑

**Ollama API 调用**：

```python
POST /api/generate
{
  "model": "llava:7b",        # config.ai_model
  "prompt": "...",            # config.ai_prompt
  "images": ["<base64>"],     # 图片 Base64 编码
  "stream": false,
  "format": "json"            # 要求 JSON 格式输出
}
```

**Prompt 设计**（`config.ai_prompt`）：
要求模型返回结构化 JSON：
```json
{
  "category": ["梗图", "表情包"],
  "tags": ["派蒙", "对话", "应急食品"],
  "work": "原神",
  "type": "screenshot",
  "has_text": true,
  "extracted_text": "任务完成"
}
```

**响应解析**：
- `_first_str()` → 处理 AI 把单值返回为列表的异常（常见于 `work` 字段）
- `_ensure_list()` → 处理 AI 把列表返回为逗号分隔字符串的异常（常见于 `tags` 字段）
- 解析失败、HTTP 错误等均返回 `None`，标记 `ai_status = 'failed'`

**源文件夹分类**：
- `_get_source_folder()` 从 `img.filepath` 提取 `scan_sources` 中的父目录名
- 将该目录名作为优先分类（prepend 到 `category` 列表最前）
- 例如 `G:\pics\phone\梗图\xxx.jpg` → 自动添加 "梗图" 到分类建议

### `pica/archiver.py` — 文件操作

- `copy_to_pending()`：从源目录复制到 `pending/{md5}.{ext}`
- `archive_image()`：从 `pending/` 复制到 `archive/{category}/{md5}.{ext}`，自动创建分类目录
- `cleanup_pending()`：归档后删除 pending 中的临时文件

### `pica/watcher.py` — 文件系统监控

- 使用 `watchdog` 库的 `Observer` 监控 `sync_dir/`
- 过滤事件类型（仅 `on_created` + `on_moved`）
- 延迟 200ms 防抖（避免大文件写入中触发）
- 回调入队到 Worker

### `pica/grouping.py` — 近似分组

- 使用 dhash（差异哈希）计算图片感知哈希
- 汉明距离 ≤ 10 视为近似（`SIMILARITY_THRESHOLD = 10`）
- `assign_similar_group()`：新图片与已有 pending 图片比较，找到最佳匹配后加入同一分组
- `batch_assign_groups()`：批量模式，一次性加载所有已有数据做比较，减少 N 次查询

### `pica/web/` — FastAPI Web 应用

**应用工厂**（`app.py`）：
- 注册 12 个路由模块，每个模块对应一个功能页面
- 注入全局状态：`cfg`, `engine`, `worker`, `cfg_file_path`
- 使用 `Jinja2Templates` 渲染 HTML 模板

**路由模块列表**（每个 `routes_*.py` 对应一个页面）：

| 路由模块 | 页面 | 核心 API |
|---------|------|---------|
| `routes_pending.py` | 待办 | `GET /pending` 列表，`GET /pending/overview` 统计，`POST /pending/{id}/confirm` 确认，`POST /pending/{id}/edit` 编辑，`POST /pending/{id}/reject` 驳回，`POST /pending/{id}/retry-ai` 重试，`POST /pending/batch-*` 批量操作 |
| `routes_archive.py` | 归档 | `GET /archive` 分页列表，`GET /archive/{id}` 详情，`POST /archive/{id}/edit` 编辑，`POST /archive/batch-edit` 批量（add_tag/remove_tag/set_category/set_work） |
| `routes_categories.py` | 分类管理 | `GET /categories/data` 树 JSON，`POST /categories/create/rename/move/delete` |
| `routes_tags.py` | 标签管理 | `GET /tags/{id}/images` 标签图片，`POST /tags/{id}/rename/merge/delete` |
| `routes_groups.py` | 分组管理 | `GET /groups/data` JSON，`POST /groups/create/rename/split/clear/delete` |
| `routes_recycle.py` | 回收站 | `GET /recycle` 列表，`POST /recycle/{id}/restore/delete-permanent`，批量操作 |
| `routes_boxes.py` | 收纳盒 | `POST /boxes/create/add/remove/finalize/delete`，`POST /boxes/batch-add` |
| `routes_scan.py` | 扫描 | `GET /scan`，`POST /scan/start`，`GET /scan/status` |
| `routes_stats.py` | 统计 | `GET /stats` 计数/分布 |
| `routes_audit.py` | 审计日志 | `GET /audit` 操作日志列表 |
| `routes_settings.py` | 设置 | `GET /settings` 配置页面，`POST /settings` 保存，目录浏览器 |
| `routes_browse.py` | 目录浏览 | `GET /api/browse?path=` 文件系统浏览（给设置页目录选择器用） |
| `routes_thumbnail.py` | 缩略图 | `GET /thumbnails/{name}` 缩略图服务，按需生成 |

**前端技术栈**：
- 模板引擎：Jinja2（服务端渲染）
- 前端框架：Alpine.js 3.14（轻量响应式，~15KB）
- AJAX 增强：htmx 1.12（局部刷新，减少页面重载）
- 样式：Apple 风格玻璃拟态 + CSS 自定义属性设计令牌
- 图标：Font Awesome 6（免费版）
- 选择机制：全局 Marquee（`#marquee-rect` + mousedown/mousemove/mouseup）
- 图片浏览：Lightbox（灯箱预览，支持键盘导航）

**设计令牌系统**（`base.html` `:root` CSS 变量）：

```css
--color-bg: #f5f5f7;          /* 背景色 */
--color-surface: rgba(255,255,255,0.72);  /* 玻璃表面 */
--color-blue: #007aff;         /* Apple 蓝 */
--color-green: #34c759;        /* Apple 绿 */
--color-red: #ff453a;            /* Apple 红 */
--color-orange: #ff9500;       /* Apple 橙 */
--radius-sm: 6px;              /* 小圆角 */
--radius-md: 12px;             /* 中圆角 */
--radius-xl: 20px;             /* 大圆角 */
--blur-bg: blur(40px);         /* 背景模糊 */
--blur-sm: blur(8px);          /* 轻微模糊 */
--shadow-sm: 0 1px 3px;        /* 小阴影 */
--shadow-lg: 0 8px 40px;       /* 大阴影 */
--font-stack: -apple-system, BlinkMacSystemFont, ...;
```

**可复用组件类**（`base.html` CSS）：

| 类 | 用途 |
|----|------|
| `.glass-card` | 毛玻璃卡片容器 |
| `.glass-btn` | 毛玻璃按钮基类 |
| `.glass-blue` / `.glass-green` / `.glass-red` / `.glass-gray` | 按钮颜色变体 |
| `.glass-input` | 毛玻璃输入框 |

## 数据流

### 完整处理链路

```
手机拍照 → Syncthing 同步 → sync_dir/
  → Watcher 检测到新文件（created / moved 事件）
    → Worker.enqueue(filepath)
      → 计算 MD5 哈希 → 查重
      → 调用 Ollama API 识别（Recognizer.recognize()）
        → 图片 Base64 → POST /api/generate
        → 解析 JSON 结果
      → copy_to_pending()：复制到 pending/{md5}.{ext}
      → generate_thumbnail()：生成缩略图
      → 计算 dhash
      → 创建 Image 记录到数据库
      → save_result_to_db()：写入 ImageCategory / ImageTag 关联表
      → assign_similar_group()：分配到近似分组
      → 数据库 commit

用户浏览器打开 http://localhost:8765
  → pending 页面显示待确认图片列表
  → 每张卡片显示：缩略图、AI 建议分类/标签、作品名、类型

用户操作：
  [确认] → POST /pending/{id}/confirm
    → archive_image()：复制 pending→archive/{category}/
    → 更新 Image status = confirmed
    → 写入 ImageCategory/Tag (source=confirmed)
    → cleanup_pending()：删除 pending 临时文件

  [驳回] → POST /pending/{id}/reject
    → Image status = recycled（软删除，文件保留）
    → cleanup_pending()

  [编辑] → POST /pending/{id}/edit
    → 更新分类/标签/作品/类型
    → ImageCategory/Tag 同步更新
```

### 双 Worker 模型

PICA 有两个并发处理路径：

| 路径 | 触发条件 | 处理内容 | 并发模型 |
|------|---------|---------|---------|
| **Worker** | Watcher 检测到 sync_dir/ 新文件 | MD5 → AI 识别 → 复制到 pending → 缩略图 → 分组 | asyncio 协程 |
| **AiProcessor** | 数据库中 `ai_status='pending'` 的图片 | AI 识别 → 结果写入 → 分组 | threading 线程轮询 |

Worker 处理完整的"文件入库"流程，AiProcessor 处理后补的 AI 识别（如之前失败的、手动添加的、配置变更后需要重识别的）。

### 设计决策

1. **复制而非移动**：原始文件从不被修改，所有操作都是复制或创建副本。safe by design。
2. **MD5 精确去重 + dhash 近似分组**：不同分层，MD5 保证系统内无完全相同的文件副本，phash 将视觉相似的图片归组便于批量处理。
3. **源文件夹作为分类**：AI 识别时自动将 `scan_sources` 中的父目录名作为优先分类建议。这利用了用户已有的文件夹组织结构。
4. **JSON 字段 + Junction 表双写**：旧的 JSON 字段保留作为向后兼容的 fallback，新的 Junction 表（ImageCategory/ImageTag）是主要查询数据源。`_migrate_json_to_relations()` 确保旧数据平滑迁移。
5. **回收站不删文件**：回收站操作只改变 `Image.status` 为 `recycled`，实际文件保留在 pending/ 中供恢复。真正的永久删除才删文件。
6. **始终开启的选择模式**：点击选中和框选共存，没有"切换选择模式"的概念。降低用户认知负荷。
7. **玻璃拟态设计系统**：CSS 自定义属性统一定义所有视觉参数，确保跨页面一致性。新页面只需引用 `var(--color-*)` 而非手写颜色值。

## 数据库关系图

```
┌──────────┐     ┌────────────────┐     ┌──────────┐
│ Category │────→│ ImageCategory  │←────│  Image   │
│ (树状层级)│     │ (多对多+source) │     │ (核心实体)│
└──────────┘     └────────────────┘     └────┬─────┘
                                             │
┌──────────┐     ┌────────────────┐          │
│   Tag    │────→│   ImageTag     │←─────────┘
│(统一标签库)│     │ (多对多+source) │
└──────────┘     └────────────────┘

┌──────────────┐     ┌──────────────────┐
│ SimilarGroup │←────│ Image.similar_id │
│ (近似分组)    │     └──────────────────┘
└──────────────┘

┌──────────────┐     ┌──────────────────┐
│ StorageBox   │────→│ StorageBoxItem   │──→ Image
│  (收纳盒)     │     │  (盒内条目)       │
└──────────────┘     └──────────────────┘

┌──────────────┐
│  AuditLog    │──→ Image (操作日志)
└──────────────┘

┌──────────────┐
│  ScanStatus  │ (key-value, 控制扫描子进程)
└──────────────┘
```

## 测试覆盖

```
tests/
├── test_scanner.py     # 扫描流程、MD5 去重、扩展名过滤
├── test_database.py    # 模型 CRUD、关联查询、状态机、迁移
├── test_recognizer.py  # AI 结果解析、异常格式处理、_first_str/_ensure_list
├── test_archiver.py    # 文件复制 cleanup_pending、archive_image
└── test_utils.py       # dhash、MD5、汉明距离、图片尺寸
```

运行：`python -m pytest tests/`

## 升级方向与规划

### P0 — 核心体验修复

| 项目 | 说明 | 技术难度 |
|------|------|---------|
| 归档页视图多样化 | 当前只有网格一种视图，仿照 pending 页增加列表/大图等 | 低（模板复用） |
| 归档页键盘快捷键 | J/K 导航，A 全选，E 编辑 | 低（Alpine 键盘事件） |
| 搜索增强 | 当前 `LIKE %q%` 搜索 5 字段，可升级到 SQLite FTS5 全文索引 | 中 |
| has_text 筛选 UI | 后端参数已支持，前端 pending 页缺少切换按钮 | 低 |
| 归档翻页保留筛选 | 翻页时用 URL 参数而非 htmx，当前会丢失筛选条件 | 中 |

### P1 — 体验打磨

| 项目 | 说明 | 技术难度 |
|------|------|---------|
| 冗余 CSS 清理 | 各页面 `extra_head` 内联样式统一到设计令牌 | 低 |
| 浮动操作栏统一 | pending/archive/recycle/box_detail 底部栏对齐 | 低 |
| 视图精简 | 9 种模式精简到 4-5 种有意义的视图 | 中 |
| 详情页增强 | AI 置信度展示、OCR 高亮、编辑功能 | 中 |

### P2 — 功能补全

| 项目 | 说明 | 技术难度 |
|------|------|---------|
| 撤销操作 | 批量操作的 Undo 支持（记录操作快照） | 中 |
| 暗色模式 | `prefers-color-scheme: dark` + 手动切换 | 低 |
| Prompt 模板 | 设置页内置多种 AI prompt 模板快速切换 | 低 |
| 多模型流水线 | 分类/标签用一个模型，OCR/文字检测用另一个 | 高 |

### P3 — 高级功能

| 项目 | 说明 | 技术难度 |
|------|------|---------|
| 全文搜索引擎 | Whoosh/Tantivy 替代 SQL LIKE 搜索 | 高 |
| AI 置信度展示 | 解析 Ollama 返回的置信度分数，UI 展示 | 中 |
| AI 队列管理 UI | 查看排队/处理中/失败任务，重排序 | 中 |
| 手工分组 | 跨状态（pending+confirmed）手工创建图片集合 | 高 |
| 图片评分 | 1-5 星评分系统 | 低 |
| 批量导出 ZIP | 选中图片打包下载 | 中 |
| 智能操作建议 | 系统自动推荐操作（相似图片合并、高频标签） | 高 |
| 统计页图表 | 趋势图、分类饼图、AI 效率 | 中 |
| 无限滚动 | 替代分页，瀑布流式加载 | 中 |

### 技术债务

| 项目 | 说明 | 影响 |
|------|------|------|
| AI 不返回置信度 | 当前 prompt 没有要求 confidence 字段，所有结果平等对待 | 用户无法判断 AI 结果可靠性 |
| 无模型热切换 | 修改 `ai_model` 后需要重启服务 | 体验不流畅 |
| 无 AI 重试策略 | 失败后标记 `failed`，没有指数退避重试 | 临时网络问题直接失败 |
| Scanner 子进程通信原始 | 通过 ScanStatus 表轮询，没有心跳检测 | 子进程挂了父进程不知道 |
| 无图片格式校验 | scanner 只检查扩展名不检查文件头 | 伪装的非图片文件会入库 |
| 缺少性能和压力测试 | 没有针对大量图片（>10万）的测试 | 大规模场景性能未知 |
