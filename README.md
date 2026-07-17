# QHAPI — 阅读 API

<p>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10+-blue" alt="Python"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.110+-green" alt="FastAPI"></a>
</p>

QHAPI 是基于 Python + FastAPI 构建的通用 API 服务。
目前提供文本文件浏览、章节解析、内容读取和远程文件下载等功能，并兼容 Legado HTTP API 协议，可配合 VS Code 插件在状态栏中阅读文本。

## 技术栈

- **语言框架**: Python 3.13+ / FastAPI
- **ASGI 服务器**: Uvicorn
- **编码检测**: chardet（自动检测 UTF-8/GBK/BIG5 等）
- **异步下载**: httpx + aiofiles

## 项目结构

```
├── app/
│   ├── config.py              # 配置管理（pydantic-settings）
│   ├── models.py              # Pydantic 请求/响应模型
│   ├── legado_models.py       # Legado HTTP API 兼容数据模型
│   ├── routers/
│   │   ├── novels.py          # 阅读 API 路由
│   │   └── legado.py          # Legado HTTP API 兼容路由
│   ├── services/
│   │   ├── file_service.py    # 文件扫描、章节解析、文本提取
│   │   ├── download_service.py# URL 下载、防同名覆盖
│   │   └── legado_service.py  # Legado 数据映射服务
│   └── utils/
│       └── encoding.py        # chardet 编码检测封装
├── novels/                    # 文本文件存放目录
├── main.py                    # 应用入口
├── requirements.txt           # Python 依赖
├── .env.example               # 配置模板
└── README.md
```

## 快速开始

### 1. 安装依赖

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 2. 配置

复制配置模板并根据需要修改：

```bash
cp .env.example .env
```

可配置项（`.env` 文件）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TEXT_FILES_DIR` | `./novels` |文本文件存放目录 |
| `TEXT_FILE_EXTENSIONS` | `.txt,.md` | 允许的文件扩展名 |
| `DEFAULT_ENCODING` | `auto` | 默认编码（auto 表示自动检测） |
| `MAX_FILE_SIZE_MB` | `50` | 下载文件大小上限（MB） |
| `DOWNLOAD_TIMEOUT_SECONDS` | `30` | 下载超时时间（秒） |

### 3. 放入文本文件

将 `.txt` 或 `.md` 格式的文本文件放入 `novels/` 目录。

### 4. 启动服务

```bash
venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

> `--reload` 参数开启热重载，修改代码后自动重启，适合开发使用。

### 5. 访问 API 文档

打开浏览器访问 `http://<服务器IP>:8000/docs` 查看 Swagger 交互式文档。

## API 接口

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/api/v1/novels` | 列出所有文本文件（分页 + 扩展名过滤） |
| `GET` | `/api/v1/novels/{filename}/chapters` | 获取文件的章节列表 |
| `GET` | `/api/v1/novels/{filename}/chapters/{chapter_number}` | 按章节获取内容（支持章节内偏移） |
| `GET` | `/api/v1/novels/{filename}/content` | 按全局偏移获取内容（支持按章节定位） |
| `POST` | `/api/v1/novels/download` | 从 URL 下载文件（自动防同名覆盖） |
| `GET` | `/health` | 健康检查 |

### 定位方式一览

| 方式 | 路径 | 参数示例 | 说明 |
|------|------|----------|------|
| 整书偏移 | `/content` | `?start=500&offset=200` | 从文件第 500 字起取 200 字 |
| 章节开头 | `/chapters/2` | （无参数） | 返回第 2 章全文 |
| 章节+偏移 | `/chapters/2` | `?start=100&offset=200` | 从第 2 章第 100 字起取 200 字 |
| 章节+长度 | `/content` | `?chapter=2&offset=300` | 从第 2 章开头起取 300 字 |
| 章节内偏移 | `/content` | `?chapter=2&start=100&offset=200` | 从第 2 章第 100 字起取 200 字 |

### 接口示例

**列出文件：**
```bash
curl http://localhost:8000/api/v1/novels
```

**章节列表：**
```bash
curl "http://localhost:8000/api/v1/novels/示例_江南烟雨.txt/chapters"
```

**从整书第 500 字起取 200 字：**
```bash
curl "http://localhost:8000/api/v1/novels/示例_江南烟雨.txt/content?start=500&offset=200"
```

**从第 2 章开头起取 200 字：**
```bash
curl "http://localhost:8000/api/v1/novels/示例_江南烟雨.txt/content?chapter=2&offset=200"
```

**从第 2 章第 100 字起取 200 字：**
```bash
curl "http://localhost:8000/api/v1/novels/示例_江南烟雨.txt/content?chapter=2&start=100&offset=200"
```

**获取第 2 章完整内容：**
```bash
curl "http://localhost:8000/api/v1/novels/示例_江南烟雨.txt/chapters/2"
```

**从第 2 章第 50 字起取 100 字（独立接口）：**
```bash
curl "http://localhost:8000/api/v1/novels/示例_江南烟雨.txt/chapters/2?start=50&offset=100"
```

**下载文件：**
```bash
curl -X POST http://localhost:8000/api/v1/novels/download \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/novel.txt"}'
```

## 功能特性

- **智能章节解析**：支持中文数字章节（第一章/第1章）、英文章节（Chapter 1）、数字序号、Markdown 标题等多种格式
- **自动编码检测**：使用 chardet 自动识别文件编码，支持 UTF-8、GBK、GB2312、BIG5 等
- **路径穿越防护**：所有文件访问均做路径校验，确保安全
- **防同名覆盖**：下载文件时若文件名已存在，自动追加 `(1)`、`(2)` 等序号
- **下载大小限制**：通过配置限制单个下载文件的大小，防止资源滥用

---

## 🔌 Legado HTTP API 兼容

本服务原生兼容 **Legado「阅读」App Web 服务协议**，可与 `yuedu_vscode_dicarbene` 等 VS Code 插件开箱即用。

### 兼容端点

| 方法 | 路径 | 参数 | 说明 |
|------|------|------|------|
| `GET` | `/getBookshelf` | 无 | 获取书架（文件列表） |
| `GET` | `/getChapterList` | `?url={bookUrl}` | 获取章节目录 |
| `GET` | `/getBookContent` | `?url={bookUrl}&index={n}` | 获取章节全文 |
| `POST` | `/saveBookProgress` | JSON Body | 保存阅读进度 |

所有响应均包装在统一格式中：
```json
{"isSuccess": true, "errorMsg": "", "data": ...}
```

### VS Code 插件配置

安装 [yuedu_vscode_dicarbene](https://github.com/Dicarbene/yuedu_vscode_dicarbene) 插件后，设置：

```json
{
  "yuedu.httpBase": "http://<服务器IP>:8000/"
}
```

即可连接本服务，在 VS Code 状态栏中阅读文本。

### 数据映射说明

| 文件/章节 | → | Legado 模型 |
|-----------|---|-------------|
| `novels/示例_江南烟雨.txt` | → | 书架上的书（name="示例_江南烟雨", bookUrl="示例_江南烟雨.txt"）|
| 文件中的"第一章" | → | 章节（title="第一章", index=0）|
| 章节全文内容 | → | `getBookContent` 返回纯文本 |

---

## 开发指南

### 环境要求

- Python 3.10+
- pip

### 本地开发

```bash
git clone https://github.com/qh25180/fish-api.git
cd fish-api
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env
venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 项目结构

```
├── app/
│   ├── config.py           # 配置管理
│   ├── models.py           # 数据模型
│   ├── legado_models.py    # Legado 兼容模型
│   ├── routers/
│   │   ├── novels.py       # 核心路由
│   │   └── legado.py       # Legado 兼容路由
│   ├── services/
│   │   ├── file_service.py     # 文件/章节处理
│   │   ├── download_service.py # 远程下载
│   │   └── legado_service.py   # Legado 映射
│   └── utils/
│       └── encoding.py    # 编码检测
├── novels/                 # 文本存放目录
├── scripts/
│   └── update-hosts.sh     # GitHub hosts 更新
├── main.py                 # 入口
├── requirements.txt
├── .env.example
└── README.md
```

### 扩展新功能

在 `app/routers/` 下新建路由文件，实现业务逻辑后在 `main.py` 中注册即可：

```python
from app.routers import your_module
app.include_router(your_module.router)
```

---

## 许可证

[MIT](LICENSE) © 2026 QHAPI
