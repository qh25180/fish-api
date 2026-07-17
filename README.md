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
| `TEXT_FILES_DIR` | `./novels` | 文本文件存放目录 |
| `TEXT_FILE_EXTENSIONS` | `.txt,.md` | 允许的文件扩展名 |
| `DEFAULT_ENCODING` | `auto` | 默认编码（auto 表示自动检测） |
| `REMOTE_DOWNLOAD_ENABLED` | `false` | 是否启用远程拉取下载接口 |
| `API_TOKEN` | `qhapi-token` | 通用 API 访问口令（留空则不验证） |
| `REMOTE_DOWNLOAD_ALLOW_INTRANET` | `false` | 是否允许远程下载内网地址的文件 |
| `UPLOAD_ENABLED` | `false` | 是否启用文件上传接口 |
| `UPLOAD_TIMEOUT_SECONDS` | `300` | 上传超时时间（秒） |
| `UPLOAD_CHUNK_SIZE_KB` | `512` | 分片上传每片大小（KB） |
| `FILE_DOWNLOAD_ENABLED` | `false` | 是否启用文件下载接口 |
| `MAX_FILE_SIZE_MB` | `50` | 单个文件大小上限（MB） |
| `DOWNLOAD_TIMEOUT_SECONDS` | `30` | 远程拉取下载超时（秒） |

### 3. 放入文本文件

将 `.txt` 或 `.md` 格式的文本文件放入 `novels/` 目录。

### 4. 启动服务

开发模式（热重载）：
```bash
venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

生产模式（带上传超时配置）：
```bash
# 方式一：使用 python 直接启动（自动读取 UPLOAD_TIMEOUT_SECONDS）
python main.py

# 方式二：使用 uvicorn 命令（需手动指定超时）
venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 300
```

> `--reload` 参数开启热重载，修改代码后自动重启，适合开发使用。
> 上传大文件时如果遇到超时，可根据文件大小适当增加 `UPLOAD_TIMEOUT_SECONDS`（默认 300 秒）。

### 5. 访问 API 文档

如果配置了 `API_TOKEN`，Swagger 文档页面需要传入 token 才能访问：

```
http://<服务器IP>:8000/docs?token=你的API_TOKEN
```

未配置 `API_TOKEN` 时直接访问 `/docs` 即可。

---

## Token 验证机制

配置 `API_TOKEN` 后，以下接口需要验证 token：

| 接口 | Token 传入方式 | 说明 |
|------|---------------|------|
| `POST /download`（远程拉取） | 请求体 `token` 字段 | 拉取 URL 文件到服务器 |
| `POST /upload`（本地上传） | 表单 `token` 字段 | 上传本地文件到服务器 |
| `GET /{filename}/download`（文件下载） | 查询参数 `?token=xxx` | 从服务器下载文件到本地 |
| `GET /read`（小说阅读） | 查询参数 `?token=xxx` | 在线阅读小说 |
| `GET /pages`（导航索引） | 查询参数 `?token=xxx` | 页面入口索引 |
| `GET /files`（文件管理） | 查询参数 `?token=xxx` | 浏览器文件管理页面 |
| `POST /{filename}/delete`（文件删除） | 查询参数 `?token=xxx` | 删除服务器上的文件 |
| `GET /docs`（Swagger 文档） | 查询参数 `?token=xxx` | 查看交互式 API 文档 |

> 不需要 Token 的接口：文本文件列表、章节列表、内容读取、健康检查等纯读取接口。
> 如 `API_TOKEN` 为空字符串，以上所有验证跳过。

---

## API 接口

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/api/v1/novels` | 列出所有文本文件（分页 + 扩展名过滤） |
| `GET` | `/api/v1/novels/{filename}/chapters` | 获取文件的章节列表 |
| `GET` | `/api/v1/novels/{filename}/chapters/{chapter_number}` | 按章节获取内容（支持章节内偏移） |
| `GET` | `/api/v1/novels/{filename}/content` | 按全局偏移获取内容（支持按章节定位） |
| `POST` | `/api/v1/novels/download` | 远程拉取 URL 文件（需 REMOTE_DOWNLOAD_ENABLED=true） |
| `POST` | `/api/v1/novels/upload` | 上传本地文件（需 UPLOAD_ENABLED=true） |
| `GET` | `/api/v1/novels/upload` | 浏览器访问的上传页面 |
| `GET` | `/api/v1/novels/pages` | 短链接索引页（所有页面入口，需 token） |
| `GET` | `/api/v1/novels/read` | 小说阅读器（选书、选章节、翻页，需 token） |
| `GET` | `/api/v1/novels/files` | 文件管理页面（分页浏览、下载、删除，需 token） |
| `GET` | `/api/v1/novels/download` | 浏览器访问的远程下载页面 |
| `GET` | `/api/v1/novels/{filename}/download` | 下载服务器文件（需 FILE_DOWNLOAD_ENABLED=true） |
| `POST` | `/api/v1/novels/{filename}/delete` | 删除服务器文件（需 FILE_DOWNLOAD_ENABLED=true） |
| `GET` | `/health` | 健康检查 |

> **Token 验证说明**：如果配置了 `API_TOKEN`，上传/下载/远程拉取接口需传入匹配的 `token`（未配置或为空则跳过验证）。默认令牌首次启动时会自动生成并输出到控制台。

> **Swagger 文档**：需传入 `?token=xxx` 访问 `/docs`。

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

**下载文件（需开启 REMOTE_DOWNLOAD_ENABLED=true）：**
```bash
# 未配口令时
curl -X POST http://localhost:8000/api/v1/novels/download \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/file.txt"}'

# 有口令时需传入 token
curl -X POST http://localhost:8000/api/v1/novels/download \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/file.txt","token":"你的口令"}'
```

**上传本地文件：**
```bash
# 未配口令时
curl -X POST http://localhost:8000/api/v1/novels/upload \
  -F "file=@/path/to/local/file.txt"

# 有口令时需传入 token
curl -X POST http://localhost:8000/api/v1/novels/upload \
  -F "file=@/path/to/local/file.txt" \
  -F "token=你的口令"
```

浏览器上传：访问 `http://<服务器IP>:8000/api/v1/novels/upload` 打开可视化上传页面。

**远程拉取文件到服务器（需开启 REMOTE_DOWNLOAD_ENABLED=true）：**
```bash
# 浏览器访问
# http://<服务器IP>:8000/api/v1/novels/download

# 未配口令时
curl -X POST http://localhost:8000/api/v1/novels/download \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/file.txt"}'

# 有口令时需传入 token
curl -X POST http://localhost:8000/api/v1/novels/download \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/file.txt","token":"你的口令"}'
```

浏览器远程下载：访问 `http://<服务器IP>:8000/api/v1/novels/download` 打开可视化下载页面。

**文件管理页面（需开启 FILE_DOWNLOAD_ENABLED=true）：**
```bash
# 浏览器访问（需传入 token）
# http://<服务器IP>:8000/api/v1/novels/files?token=你的口令
```

**下载服务器文件到本地（需开启 FILE_DOWNLOAD_ENABLED=true）：**
```bash
# 浏览器直接访问
# http://<服务器IP>:8000/api/v1/novels/示例_江南烟雨.txt/download?token=你的口令

# curl 下载
curl -o output.txt "http://localhost:8000/api/v1/novels/%E7%A4%BA%E4%BE%8B_%E6%B1%9F%E5%8D%97%E7%83%9F%E9%9B%A8.txt/download?token=你的口令"
```

## 功能特性

- **智能章节解析**：支持中文数字章节（第一章/第1章）、英文章节（Chapter 1）、数字序号、Markdown 标题等多种格式
- **自动编码检测**：使用 chardet 自动识别文件编码，支持 UTF-8、GBK、GB2312、BIG5 等
- **路径穿越防护**：所有文件访问均做路径校验，确保安全
- **防同名覆盖**：下载文件时若文件名已存在，自动追加 `(1)`、`(2)` 等序号
- **下载大小限制**：通过配置限制单个下载文件的大小，防止资源滥用
- **分片上传**：大文件自动切分为多个小块分批传输，支持断点续传，避免超时失败

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
