# PICA — Personal Image Collection Agent

个人图片分类管理工具。通过 Syncthing 从手机同步图片到电脑，自动用 Ollama 视觉模型进行 AI 识别（分类/标签/作品/类型/文字检测），支持 MD5 精确去重和 dhash 近似分组，提供 FastAPI Web 界面进行人工确认和归档。

## 技术背景与设计理念

### 解决了什么问题？

手机相册中的图片数量爆炸式增长，手动整理耗时巨大。现有方案要么完全手动（文件管理器），要么黑箱式自动整理（Google Photos 等）— 用户无法控制分类逻辑、无法修正 AI 错误、无法批量编辑。

PICA 的设计理念介于两者之间：**AI 辅助 + 人工确认**。AI 做粗分类和标签提取（可纠错），人做最终审批和微调（零代码操作）。

### 核心技术选择

| 技术 | 选择理由 |
|------|---------|
| **Ollama** | 本地运行，隐私安全（图片不离机），离线可用，无需 GPU 也可用 CPU 跑 |
| **SQLite** | 单用户场景足够，零运维，备份即拷贝文件 |
| **FastAPI** | Python 生态，异步原生，依赖少，部署简单 |
| **Alpine.js** | 轻量（<15KB），无需构建工具链，直接写 HTML 就行 |
| **dhash** | 差异哈希，对缩略图/水印/轻微编辑的鲁棒性优于 MD5 |

### 设计原则

1. **永不修改源文件** — 所有操作都是复制，原始文件不受影响
2. **隐私优先** — 所有 AI 推理在本地完成，图片不离开你的电脑
3. **渐进式操作** — 自动扫描 → AI 建议 → 人工确认 → 归档，每步可干预
4. **始终可选** — 所有操作都有选中状态，无需切换模式

## Ollama 设置

### 安装 Ollama

```bash
# Windows
# 从 https://ollama.com 下载安装包，安装后 Ollama 自动注册为系统服务

# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

### 拉取视觉模型

Ollama 安装后，需要拉取至少一个支持图片输入的视觉模型（Vision Language Model, VLM）：

```bash
# 推荐轻量级（CPU 可用）：
ollama pull llava:7b          # 7B 参数，质量不错，CPU 慢但能用
ollama pull moondream:latest   # 1.6B，极轻量，CPU 友好，中文支持一般

# 推荐中量级（需要一定 GPU 显存）：
ollama pull llava:13b           # 13B，质量更好，需要 ~8GB 显存
ollama pull gemma-3-vision:12b  # Google Gemma 3 Vision，中文支持优秀

# 最轻量（快速 CPU 推理）：
ollama pull llava:latest        # llava 的默认标签（通常 7B）
ollama pull minicpm-v:latest    # 2B 参数，中文优化
```

### 启动 Ollama 服务

```bash
# Ollama 默认在安装后自动以服务运行：
#   Windows: 系统托盘有 Ollama 图标
#   macOS/Linux: 后台守护进程

# 手动启动（如果需要）：
ollama serve

# 验证服务是否正常：
curl http://localhost:11434/api/generate -d '{"model":"llava:7b","prompt":"hi","stream":false}'

# 验证视觉模型是否可用：
curl http://localhost:11434/api/generate -d '{
  "model": "llava:7b",
  "prompt": "Describe this image briefly",
  "images": ["<base64_encoded_image>"],
  "stream": false
}'

# 查看已拉取的模型列表：
ollama list
```

### 模型选择建议

| 模型 | 参数 | 最少显存 | CPU 推理速度 | 中文质量 | 适用场景 |
|------|------|---------|-------------|---------|---------|
| `moondream` | 1.6B | 1GB | ★★★★ 较快 | ★★ 一般 | 快速分类，低配机器 |
| `minicpm-v` | 2B | 1.5GB | ★★★ 中等 | ★★★★ 优秀 | 中文图片分类 |
| `llava:7b` | 7B | 4GB | ★★ 较慢 | ★★★ 良好 | 默认首选，平衡之选 |
| `llava:13b` | 13B | 8GB | ★ 很慢 | ★★★ 良好 | 质量优先，有 GPU |
| `gemma-3-vision:12b` | 12B | 8GB | ★ 很慢 | ★★★★★ 最佳 | 中文场景最佳质量 |
| `qwen2-vl:7b` | 7B | 4GB | ★★ 较慢 | ★★★★★ 最佳 | 中文识别最准 |
| `llava-llama3:8b` | 8B | 4GB | ★★ 较慢 | ★★★ 良好 | 综合能力强 |

> **注意**：CPU 推理 7B 模型每张图约 10-60 秒，建议用 GPU 或选择小模型。配置在 `config.json` 的 `ai_timeout` 调大（默认 120 秒）。

### 修改 PICA 配置使用对应模型

编辑 `config.json`：

```json
{
  "ollama_url": "http://localhost:11434/api/generate",
  "ai_model": "qwen2-vl:7b",
  "ai_timeout": 120
}
```

> 如果 Ollama 在不同机器上运行，`ollama_url` 可改为 `http://<ip>:11434/api/generate`。

## 快速开始

### 前置要求

- Python 3.11+
- [Ollama](https://ollama.com/) 已安装并运行（见上节），已拉取视觉模型

### 安装

```bash
# 克隆仓库
git clone <repo-url> && cd PICA

# 创建虚拟环境
python -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements.txt

# macOS/Linux
# source .venv/bin/activate && pip install -r requirements.txt
```

### 配置

编辑 `config.json`（会自动从 `config.example.json` 复制）：

```json
{
  "ollama_url": "http://localhost:11434/api/generate",
  "ai_model": "llava:7b",
  "host": "0.0.0.0",
  "port": 8765,
  "scan_sources": ["D:\\pics\\phone"],
  "categories": ["人物", "风景", "食物", "宠物", "其他"]
}
```

完整配置项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ollama_url` | `http://localhost:11434/api/generate` | Ollama API 地址，可改为远程地址 |
| `ai_model` | `llava:7b` | 视觉模型名，需已 `ollama pull` |
| `ai_timeout` | `120` | AI 推理超时（秒），CPU 跑大模型需要调大 |
| `host` | `0.0.0.0` | Web 监听地址，`0.0.0.0` 允许局域网访问 |
| `port` | `8765` | Web 端口 |
| `scan_sources` | `[]` | 扫描源目录列表，多个目录自动递归扫描 |
| `categories` | `["人物","风景","食物","宠物","其他"]` | 预置分类，AI 也可创建新分类 |
| `ai_prompt` | （长 prompt） | 控制 AI 分析指令，可自定义微调 |
| `thumbnail_size` | `[256, 256]` | 缩略图尺寸 |
| `thumbnail_quality` | `85` | 缩略图 JPEG 质量 |
| `watcher_interval` | `1.0` | 文件监控间隔（秒） |
| `worker_max_concurrent` | `1` | 同时处理数，多 GPU 可调大 |
| `allowed_extensions` | `.jpg,.jpeg,.png,.webp,.bmp,.tiff,.tif` | 允许的文件扩展名 |

### 启动

```bash
# 方式一：一体模式（Web + Scanner 子进程 + AI 处理）
python -m pica

# 方式二：仅 Web（不含 Scanner 子进程，需手动扫描）
python -m pica web

# 方式三：仅 Scanner（独立扫描进程）
python -m pica scanner

# 方式四：开发模式（热重载）
python -m pica --reload

# 方式五：指定配置文件
python -m pica --config myconfig.json

# 方式六：使用启动脚本（Windows）
.\scripts\start.ps1
```

启动后访问 `http://localhost:8765`。

### 3 种运行模式的差异

| 模式 | 扫描 | Web UI | AI 识别 | 适用场景 |
|------|------|--------|---------|---------|
| `all`（默认） | 子进程自动扫描 | 启 | 启 | 完整使用，开箱即用 |
| `web` | 手动在 /scan 页面触发 | 启 | 启 | 希望手动控制扫描时机 |
| `scanner` | 独立扫描 | 不启 | 不启 | 仅扫描入库，配合外部服务 |

### 工作流程

```
1. 手机 → Syncthing 自动同步到电脑 sync_dir/
2. PICA Watcher 检测到新文件 → Worker 入队
3. Worker 调用 Ollama AI 模型分析图片内容
4. 图片进入 pending/，Web UI 待办页显示 AI 结果
5. 用户在 Web UI 浏览/确认/编辑/驳回
6. 确认的图片归档到 archive/{category}/
7. 驳回的图片进入回收站（软删除，可恢复）
```

## 打包为桌面应用

### 使用 Tauri v2 打包

```bash
# 前置条件
# 1. 安装 Rust: https://rustup.rs
# 2. 安装 Tauri CLI: cargo install tauri-cli --version "^2.0"
# 3. Windows 需要安装 WiX Toolset (https://wixtoolset.org) 或 NSIS

# 开发模式（热重载 Web + 原生窗口）
.\scripts\tauri-dev.ps1
# 或手动:
# cargo tauri dev

# 生产构建（生成安装包）
.\scripts\tauri-build.ps1
# 或手动:
# cargo tauri build

# 安装包路径:
# Windows: src-tauri/target/release/bundle/msi/PICA_0.2.0_x64.msi
#          或 src-tauri/target/release/bundle/nsis/PICA_0.2.0_x64-setup.exe
# macOS:   src-tauri/target/release/bundle/dmg/PICA_0.2.0_x64.dmg
# Linux:   src-tauri/target/release/bundle/deb/pica_0.2.0_amd64.deb
```

Tauri 桌面应用的启动流程：

```
用户双击桌面图标
  → Rust 入口 (main.rs)
    → spawn Python 子进程 (python -m pica web)
    → 每隔 500ms 轮询 http://127.0.0.1:8765/pending
    → 服务就绪后打开 WebView 加载 http://127.0.0.1:8765
    → 用户关闭窗口时 kill Python 子进程
```

### 手动打包 Python 后端（可选，不含 Tauri）

```bash
# 使用 PyInstaller 打包为单文件
pip install pyinstaller
pyinstaller --onefile --name pica-server ^
  --hidden-import pica ^
  --hidden-import pica.__main__ ^
  --hidden-import pica.web.app ^
  --hidden-import pica.web.routes_pending ^
  --hidden-import pica.web.routes_archive ^
  --hidden-import pica.web.routes_settings ^
  --hidden-import pica.web.routes_scan ^
  --hidden-import pica.web.routes_browse ^
  --hidden-import pica.web.routes_tags ^
  --hidden-import pica.web.routes_groups ^
  --hidden-import pica.web.routes_categories ^
  --hidden-import pica.web.routes_recycle ^
  --hidden-import pica.web.routes_boxes ^
  --hidden-import pica.web.routes_audit ^
  --hidden-import pica.web.routes_stats ^
  --hidden-import pica.web.routes_thumbnail ^
  --collect-all pica
```

## 页面功能总览

| 页面 | 路由 | 功能 | 状态 |
|------|------|------|------|
| 待办 | `/pending` | AI 结果浏览，确认/驳回/编辑/重试AI，9 种视图 | ✅ 完善 |
| 归档 | `/archive` | 浏览已归档图片，搜索，批量编辑分类/标签 | ✅ 完善 |
| 分类管理 | `/categories` | 树状导航，CRUD，重命名/移动/删除 | ✅ 完善 |
| 标签管理 | `/tags` | 标签库管理，预览标签图片，合并/重命名/删除 | ✅ 完善 |
| 分组管理 | `/groups` | phash 近似分组查看，新建/合并/拆分/重命名 | ✅ 完善 |
| 回收站 | `/recycle` | 查看已驳回图片，恢复或永久删除 | ✅ 完善 |
| 收纳盒 | `/boxes` | 临时收纳盒，拖入图片后批量归档 | ✅ 完善 |
| 扫描 | `/scan` | 手动触发扫描，查看扫描状态 | ✅ 完善 |
| 统计 | `/stats` | 图片总数/分布统计 | ✅ 基本 |
| 审计 | `/audit` | 操作日志（AI/用户/批量） | ✅ 完善 |
| 设置 | `/settings` | 修改配置，浏览目录 | ✅ 完善 |
| 图片详情 | `/pending/{id}` | 大图预览，相似图片，编辑 | ✅ 完善 |

## 页面路由一览

| 路由 | 方法 | 功能 |
|------|------|------|
| `/` | GET | 重定向到 `/pending` |
| `/pending` | GET | 待办列表（支持 view/group/sort/filter 参数） |
| `/pending/overview` | GET | 待办概览（分类/标签/作品/类型统计 JSON） |
| `/pending/{id}` | GET | 图片详情页 |
| `/pending/{id}/data` | GET | 图片数据 JSON |
| `/pending/{id}/confirm` | POST | 确认单张（归档） |
| `/pending/{id}/edit` | POST | 编辑单张 |
| `/pending/{id}/reject` | POST | 驳回单张 |
| `/pending/{id}/retry-ai` | POST | 重试 AI |
| `/pending/batch-confirm` | POST | 批量确认 |
| `/pending/batch-edit` | POST | 批量编辑 |
| `/pending/batch-reject` | POST | 批量驳回 |
| `/pending/batch-retry-ai` | POST | 批量重试 AI |
| `/archive` | GET | 归档列表（支持 category/tag/q/page 参数） |
| `/archive/{id}` | GET | 归档图片详情 |
| `/archive/{id}/edit` | POST | 编辑归档图片 |
| `/archive/batch-edit` | POST | 批量编辑归档（add_tag/remove_tag/set_category/set_work） |
| `/categories` | GET | 分类管理页 |
| `/categories/data` | GET | 分类树 JSON |
| `/categories/create` | POST | 新建分类 |
| `/categories/{id}/rename` | POST | 重命名分类 |
| `/categories/{id}/move` | POST | 移动分类 |
| `/categories/{id}/delete` | POST | 删除分类 |
| `/categories/{id}/images` | GET | 分类下的图片 |
| `/tags` | GET | 标签管理页 |
| `/tags/{id}/images` | GET | 标签下的图片 |
| `/tags/{id}/rename` | POST | 重命名标签 |
| `/tags/{id}/merge` | POST | 合并标签 |
| `/tags/{id}/delete` | POST | 删除标签 |
| `/recycle` | GET | 回收站列表 |
| `/recycle/{id}/restore` | POST | 恢复图片 |
| `/recycle/{id}/delete-permanent` | POST | 永久删除 |
| `/recycle/batch-restore` | POST | 批量恢复 |
| `/recycle/batch-delete-permanent` | POST | 批量永久删除 |
| `/boxes` | GET | 收纳盒列表 |
| `/boxes/{id}` | GET | 收纳盒详情 |
| `/boxes/create` | POST | 新建收纳盒 |
| `/boxes/{id}/rename` | POST | 重命名收纳盒 |
| `/boxes/{id}/add` | POST | 添加图片到收纳盒 |
| `/boxes/{id}/remove` | POST | 移除图片 |
| `/boxes/{id}/finalize` | POST | 归档盒内所有图片 |
| `/boxes/{id}/delete` | POST | 删除收纳盒 |
| `/boxes/batch-add` | POST | 批量添加到收纳盒 |
| `/groups` | GET | 分组管理页 |
| `/groups/data` | GET | 分组 JSON |
| `/groups/create` | POST | 新建分组 |
| `/groups/{id}/rename` | POST | 重命名分组 |
| `/groups/{id}/split` | POST | 拆分分组 |
| `/groups/{id}/clear` | POST | 清空分组 |
| `/groups/{id}/delete` | POST | 删除分组 |
| `/scan` | GET | 扫描页 |
| `/scan/start` | POST | 触发扫描 |
| `/scan/status` | GET | 扫描状态 JSON |
| `/stats` | GET | 统计页 |
| `/audit` | GET | 审计日志 |
| `/settings` | GET/POST | 设置页 |
| `/api/browse` | GET | 浏览文件系统（目录选择器用） |
| `/thumbnails/{name}` | GET | 缩略图服务 |

## 核心功能详解

### 选择机制

- **始终开启的点击选中**：点击图片卡片切换选中状态，不区分"选择模式"和"浏览模式"
- **框选（Marquee）**：在图片网格上按住鼠标拖拽，自动选中矩形范围内的所有图片，忽略工具栏/滚动条等交互元素
- **拖拽到收纳盒**：选中后拖拽到底部收纳盒，支持多盒拖拽自动放入第一个并展开所有盒

### 收纳盒（Box Tray）

- 全局底部栏，所有图片页面可见
- 拖拽图片或选中后点击"加入收纳盒"
- 创建/折叠/展开/清空收纳盒
- 一键归档盒内所有图片

### AI 识别流程

```
图片入库 → ai_status='pending'
  → AiProcessor 轮询（每 2 秒批量取 5 张）
  → ai_status='processing'
  → 调用 Ollama API：
      POST /api/generate
      { model, prompt, images: [base64], stream: false, format: json }
  → 解析返回 JSON：
      { category: [], tags: [], work: "", type: "",
        has_text: bool, extracted_text: "" }
  → 源文件夹名自动作为优先分类
  → 写入 ImageCategory / ImageTag 关联表
  → assign_similar_group() 按 phash 分组
  → ai_status='done' / 'failed'
```

### 缩略图

- 格式：`/thumbnails/{md5_hash}_256.jpg`（小）和 `{md5_hash}_1024.jpg`（大）
- 首次请求时自动生成，后续直接返回静态文件
- 生成路径：`thumbnails/` 目录

### 设计风格

Apple 风格玻璃拟态设计（Glassmorphism）：
- CSS 自定义属性设计令牌系统（`--color-*`, `--radius-*`, `--blur-*`, `--shadow-*`）
- 可复用组件类：`.glass-card`, `.glass-btn`, `.glass-blue/green/red/gray`
- Toast 消息通知系统（全局 JS 函数，支持 success/error/info/warning）
- macOS 风格统一标题栏和交通灯按钮

## 数据库模型

```
Image:          filename, filepath, md5_hash, phash, status, ai_status,
                suggested_category/tags (JSON), confirmed_category/tags (JSON),
                work_name, image_type, has_text, extracted_text, ai_model, etc.
Category:       id, parent_id, name, sort_order (无限层级树)
Tag:            id, name, color, usage_count (全局统一标签库)
ImageCategory:  image_id, category_id, source (ai_suggested / confirmed)
ImageTag:       image_id, tag_id, source (ai_suggested / confirmed)
SimilarGroup:   id, name, phash_ref (近似分组)
AuditLog:       image_id, action, old_value, new_value, source (ai/user/batch)
StorageBox:     id, name, color (收纳盒)
StorageBoxItem: box_id, image_id (收纳盒内容)
ScanStatus:     key-value 表，控制扫描子进程
```

## 项目结构

```
PICA/
├── pica/                    # Python 后端
│   ├── __main__.py          # CLI 入口（argparse，3 种模式）
│   ├── config.py            # 配置管理（dataclass + JSON reload）
│   ├── database.py          # SQLAlchemy ORM 模型（12 张表）
│   ├── scanner.py           # 文件扫描 + MD5 去重
│   ├── scanner_worker.py    # 独立扫描子进程
│   ├── recognizer.py        # Ollama API 调用 + 结果解析
│   ├── ai_processor.py      # 后台 AI 批量处理线程
│   ├── archiver.py          # 文件复制/清理
│   ├── watcher.py           # Watchdog 文件监控
│   ├── worker.py            # 异步任务队列
│   ├── grouping.py          # dhash 近似分组
│   ├── thumbnail.py         # 缩略图生成
│   ├── utils.py             # MD5/dhash/图片尺寸
│   ├── process.py           # Scanner 子进程生命周期管理
│   └── web/                 # FastAPI Web 应用
│       ├── app.py           # 应用工厂（注册 12 个路由模块）
│       ├── routes_*.py      # 各页面路由（12 个路由模块）
│       └── templates/       # Jinja2 模板（26 个）
├── src-tauri/               # Tauri v2 桌面壳
│   ├── src/lib.rs           # Rust: 启动 Python 进程 + WebView
│   ├── src/main.rs          # Rust 入口
│   ├── webview/index.html   # 启动加载页
│   ├── tauri.conf.json      # Tauri 配置
│   └── Cargo.toml           # Rust 依赖
├── scripts/                 # 启动/构建脚本
├── tests/                   # pytest 测试（13 个）
├── docs/                    # 设计文档
├── config.example.json      # 配置示例
└── requirements.txt         # Python 依赖
```

## 开发

```bash
# 安装依赖
pip install -r requirements.txt

# 运行测试
python -m pytest tests/

# 开发模式启动（自动重载）
python -m pica --reload

# Tauri 开发模式
cargo tauri dev
```

## 升级方向与待办事项

### 近期可做（优先级 P0-P1）

- [ ] 归档页视图多样化 — 类似待办页的 9 种视图模式
- [ ] 归档页键盘快捷键 — `J/K` 上/下选择，`A` 全选，`E` 编辑
- [ ] 搜索增强 — 全文搜索（current: 仅 `LIKE %q%` 搜索 5 个字段）
- [ ] `has_text` 筛选 UI — 后端参数已支持，前端缺少切换按钮
- [ ] 归档页保留筛选参数翻页 — 目前翻页会丢失筛选条件

### 中期规划（P2）

- [ ] 减少冗余 CSS — 各页面 `extra_head` 中的内联样式统一到设计令牌
- [ ] 统一浮动操作栏样式 — pending/archive/recycle/box_detail 的底部栏视觉统一
- [ ] View 模式精简 — 从 9 种合并为 4-5 种有意义视图（大图标/中图标/列表/瀑布流）
- [ ] 图片详情页 `/detail.html` 增强 — AI 置信度展示、OCR 文字高亮、编辑功能补全
- [ ] 设置页 AI prompt 模板选择器 — 预设几种 prompt 风格快速切换

### 远期规划（P3）

- [ ] **撤销操作** — 支持 Ctrl+Z 撤销最近的批量操作
- [ ] **暗色模式** — CSS 变量支持 `prefers-color-scheme: dark`
- [ ] **多模型流水线** — 标签/分类与 OCR/质量检测用不同模型分步处理
- [ ] **全文搜索引擎** — 集成 Whoosh/Tantivy 替代 SQL LIKE 搜索
- [ ] **AI 置信度展示** — Ollama 返回置信度分数，UI 用星级/进度条显示
- [ ] **AI 队列管理 UI** — 查看排队/处理中/失败的任务，支持重排序
- [ ] **手工分组** — 允许用户跨状态（pending+confirmed）手动创建图片集合
- [ ] **图片收藏/评分** — 1-5 星评分系统，精选图片
- [ ] **批量导出/ZIP** — 选中图片打包下载
- [ ] **智能操作建议** — 系统自动推荐操作（相似图片合并、高频标签关联等）
- [ ] **统计页增强** — 趋势图、AI 效率统计、分类分布图表
