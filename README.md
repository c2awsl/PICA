# PICA — Personal Image Collection Agent

个人图片分类管理工具。通过 Syncthing 从手机同步图片到电脑，自动用 Ollama 视觉模型进行 AI 识别（分类/标签/作品/类型/文字检测），支持 MD5 精确去重和 dhash 近似分组，提供 FastAPI Web 界面进行人工确认和归档。

## 系统架构

```
手机 → Syncthing → sync_dir/ → scanner → pending/ → Web UI → archive/
                                → AI 识别 (Ollama)
```

- **Syncthing**：手机图片自动同步到 `sync_dir/`
- **Scanner**：扫描源目录，检测新图片，MD5 去重后复制到 `pending/`
- **AI 识别**：Ollama 视觉模型分析图片，返回分类、标签、作品名、图片类型、文字检测
- **Web UI**：FastAPI + Jinja2 + Alpine.js，提供待办确认、归档管理、分类/标签管理、回收站等
- **Tauri v2 桌面壳**：将 Web UI 打包为原生桌面应用（Windows .msi/.exe, macOS .dmg）

## 快速开始

### 前置要求

- Python 3.11+
- [Ollama](https://ollama.com/) 已安装并运行，已拉取视觉模型（如 `llava:7b`）

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

| 配置项 | 说明 |
|--------|------|
| `ollama_url` | Ollama API 地址 |
| `ai_model` | 视觉模型名（如 `llava:7b`, `gemma-3-vision:12b`） |
| `host` / `port` | Web 服务监听地址和端口 |
| `scan_sources` | 扫描源目录列表（支持多个），新图片从这些目录复制到 pending |
| `categories` | 预置分类列表，AI 也可以生成不在列表中的新分类 |
| `ai_prompt` | 控制 AI 分析图片的指令模板 |
| `ai_timeout` | AI 推理超时（秒），默认 120 |

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
| `all`（默认） | 子进程自动扫描 | 启 | 启 | 完整使用 |
| `web` | 手动在 /scan 页面触发 | 启 | 启 | 希望手动控制扫描时机 |
| `scanner` | 独立扫描 | 不启 | 不启 | 仅扫描入库，配合外部服务 |

## 打包为桌面应用

### 使用 Tauri v2 打包

```bash
# 前置条件
# 1. 安装 Rust: https://rustup.rs
# 2. 安装 Tauri CLI: cargo install tauri-cli --version "^2.0"
# 3. Windows 需要安装 WiX Toolset 或 NSIS

# 开发模式（热重载 Web + 原生窗口）
.\scripts\tauri-dev.ps1
# 或手动:
# cd src-tauri && cargo tauri dev

# 生产构建（生成安装包）
.\scripts\tauri-build.ps1
# 或手动:
# cargo tauri build

# 安装包路径:
# Windows: src-tauri/target/release/bundle/msi/PICA_0.2.0_x64.msi
# macOS:   src-tauri/target/release/bundle/dmg/PICA_0.2.0_x64.dmg
# Linux:   src-tauri/target/release/bundle/deb/pica_0.2.0_amd64.deb
```

Tauri 桌面应用的启动流程：
1. 用户打开桌面应用
2. Tauri Rust 后端自动运行 `python -m pica web` 作为子进程
3. 轮询 `http://127.0.0.1:8765` 等待服务就绪
4. WebView 加载 `http://127.0.0.1:8765`
5. 关闭窗口时自动终止 Python 子进程

### 手动打包 Python 后端（可选）

```bash
# 使用 PyInstaller 打包为单文件（用于分发不含 Tauri）
pip install pyinstaller
pyinstaller --onefile --name pica-server --hidden-import pica pica.__main__
```

## 页面功能总览

| 页面 | 路由 | 功能 |
|------|------|------|
| 待办 | `/pending` | 查看 AI 识别结果，确认/驳回/编辑新图片，9 种视图，批量操作 |
| 归档 | `/archive` | 浏览已归档图片，按分类/标签筛选，批量编辑 |
| 分类管理 | `/categories` | 树状分类导航，新建/重命名/移动/删除分类 |
| 标签管理 | `/tags` | 统一标签库管理，查看标签下的图片，合并/重命名/删除 |
| 分组管理 | `/groups` | 按 phash 自动分组，手动创建/合并/拆分/重命名分组 |
| 回收站 | `/recycle` | 查看已驳回图片，恢复或永久删除 |
| 收纳盒 | `/boxes` | 创建临时收纳盒，从各页面拖入图片，批量归档 |
| 扫描 | `/scan` | 手动触发扫描操作，查看扫描进度 |
| 统计 | `/stats` | 图片总数、待处理数、归档数、分类分布等统计 |
| 审计 | `/audit` | 查看所有操作日志（AI 识别、用户编辑、批量操作等） |
| 设置 | `/settings` | 修改配置（Ollama 地址、模型、扫描源、网络等） |

## 核心功能

### 数据流

```
scan_sources → scanner（MD5 去重） → pending/ → AI 识别（Ollama）
                                                        ↓
                                              Web UI 人工确认
                                                        ↓
                                              archive/{category}/ （复制归档）
```

- **扫描**：监控 `scan_sources` 目录，检测新图片文件，计算 MD5 去重，将新图片复制到 `pending/`
- **AI 识别**：异步队列，依次调用 Ollama 视觉模型，提取分类、标签、作品名、图片类型、是否有文字
- **归档**：人工确认后，图片从 `pending/` 复制到 `archive/{category}/`，并记录分类/标签关系到数据库
- **源文件夹作为分类**：AI 识别时自动将图片所在源目录的文件夹名称作为优先分类建议

### 选择机制

- **始终开启的点击选中**：点击图片卡片切换选中状态，不区分"选择模式"和"浏览模式"
- **框选（Marquee）**：在图片网格上按住鼠标拖拽，自动选中矩形范围内的所有图片
- **拖拽到收纳盒**：选中后拖拽到底部收纳盒，支持多盒拖拽会自动放入第一个并展开所有盒

### 收纳盒（Box Tray）

- 全局底部栏，所有图片页面可见
- 拖拽图片或选中后点击"加入收纳盒"
- 创建/折叠/展开/清空收纳盒
- 一键将盒内所有图片归档

### 设计风格

Apple 风格玻璃拟态设计（Glassmorphism）：
- 半透明毛玻璃表面（`backdrop-filter: blur`）
- 柔和阴影和圆角
- macOS 风格统一标题栏和交通灯按钮
- CSS 自定义属性设计令牌系统（`--color-*`, `--radius-*`, `--blur-*`, `--shadow-*`）
- Toast 消息通知系统

## 目录结构

```
PICA/
├── pica/                    # Python 后端
│   ├── __main__.py          # 入口（CLI 解析、启动逻辑）
│   ├── config.py            # 配置管理（dataclass + JSON 文件）
│   ├── database.py          # 数据库模型（SQLAlchemy + SQLite）
│   ├── scanner.py           # 扫描逻辑（文件检测、MD5 去重）
│   ├── scanner_worker.py    # 独立扫描进程
│   ├── recognizer.py        # AI 识别逻辑（Ollama API 调用 + 结果解析）
│   ├── ai_processor.py      # AI 处理队列管理
│   ├── archiver.py          # 归档逻辑（文件复制、状态更新）
│   ├── watcher.py           # 文件系统监控（Watchdog）
│   ├── worker.py            # 异步任务队列
│   ├── grouping.py          # phash 近似分组
│   ├── thumbnail.py         # 缩略图生成
│   ├── utils.py             # 工具函数
│   ├── process.py           # Scanner 子进程管理
│   └── web/                 # FastAPI Web 应用
│       ├── app.py           # FastAPI 应用工厂
│       ├── routes_*.py      # 各页面路由
│       └── templates/       # Jinja2 模板（26 个）
├── src-tauri/               # Tauri v2 桌面壳
│   ├── src/lib.rs           # Rust 主逻辑（启动 Python 进程、等待服务）
│   ├── src/main.rs          # 入口
│   ├── webview/index.html   # Tauri WebView 加载页
│   ├── tauri.conf.json      # Tauri 配置
│   └── Cargo.toml           # Rust 依赖
├── scripts/                 # 辅助脚本
│   ├── start.ps1            # 启动脚本
│   ├── tauri-dev.ps1        # Tauri 开发模式
│   ├── tauri-build.ps1      # Tauri 生产构建
│   └── init_db.py           # 数据库初始化
├── tests/                   # 测试（pytest）
│   ├── test_archiver.py
│   ├── test_database.py
│   ├── test_recognizer.py
│   ├── test_scanner.py
│   └── test_utils.py
├── config.example.json      # 配置示例
├── requirements.txt         # Python 依赖
└── data/                    # 运行时数据（运行时创建）
    └── pica.db              # SQLite 数据库
```

## 开发

```bash
# 安装开发依赖
pip install -r requirements.txt

# 运行测试
python -m pytest tests/

# 开发模式启动（自动重载）
python -m pica --reload

# Tauri 开发（需要 Rust）
cargo tauri dev
```

## 数据库模型

| 表 | 说明 |
|----|------|
| `Image` | 图片记录（MD5、phash、状态、AI 结果等 30+ 字段） |
| `Category` | 层级分类树（parent_id 自引用） |
| `ImageCategory` | 图片-分类关联（含 source: ai_suggested/confirmed） |
| `Tag` | 统一标签库 |
| `ImageTag` | 图片-标签关联（含 source） |
| `SimilarGroup` | phash 近似分组 |
| `AuditLog` | 操作审计日志 |
| `StorageBox` / `StorageBoxItem` | 收纳盒及内容 |
| `ScanStatus` | 扫描状态 |
