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
- **拼音转换**: pypinyin（中文文件名转拼音）
- **元数据提取**: 书名/作者自动识别（`《》` 书名号、文件名、正文头部）
- **浏览器阅读器**: 原生 HTML/CSS/JS，无前端依赖，支持移动端

## 项目结构

```
├── app/
│   ├── config.py              # 配置管理（pydantic-settings）
│   ├── security.py            # 统一认证层（Bearer/Cookie 多通道验证）
│   ├── models.py              # Pydantic 请求/响应模型
│   ├── legado_models.py       # Legado HTTP API 兼容数据模型
│   ├── sources/               # 搜索源插件体系
│   │   ├── __init__.py        # 基类 + 注册表
│   │   ├── source_a.py        # 源A（HTML 解析）
│   │   └── source_b.py        # 源B（API）
│   ├── routers/
│   │   ├── novels.py          # 阅读 API 路由
│   │   ├── search.py          # 搜索 API 路由
│   │   └── legado.py          # Legado HTTP API 兼容路由
│   ├── templates/             # 前端页面模板（Jinja2）
│   │   ├── index.html         # 导航索引页
│   │   ├── reader.html        # 文本阅读器
│   │   ├── files.html         # 文件管理页
│   │   ├── upload.html        # 上传页
│   │   ├── download.html      # 远程下载页
│   │   └── search.html        # 搜索页
│   ├── static/                # 前端静态资源（CSS/JS）
│   │   ├── css/               # 各页面样式
│   │   └── js/                # qhapi.js 通用工具 + 各页面逻辑
│   ├── services/
│   │   ├── file_service.py    # 文件扫描、章节解析、文本提取、作者识别
│   │   ├── download_service.py# URL 下载、防同名覆盖
│   │   └── legado_service.py  # Legado 数据映射 + 进度持久化
│   └── utils/
│       ├── encoding.py        # chardet 编码检测封装
│       ├── meta_util.py       # 书名/作者元数据提取
│       └── pinyin_util.py     # 中文转拼音工具
├── novels/                    # 文本文件存放目录
├── scripts/
│   ├── qhapi_book.sh          # 命令行搜索下载脚本
│   └── update-hosts.sh        # GitHub hosts 定时更新
├── main.py                    # 应用入口
├── requirements.txt           # Python 依赖
├── .env.example               # 配置模板
├── Dockerfile                 # 容器镜像构建
├── .dockerignore              # 构建上下文排除清单
├── docker-compose.yml         # Docker Compose 编排
└── README.md
```

## 快速开始

### 0. 使用 Docker 一键部署（推荐）

无需手动安装 Python 依赖，一条命令即可从项目直接构建并启动容器（需已安装 Docker 与 Docker Compose 插件）：

```bash
# 1. 准备配置（首次）
cp .env.example .env

# 2. 构建镜像并启动容器
cd /usr/local/code/fish-api
docker compose up -d

# 3. 查看运行状态与日志
docker compose ps
docker compose logs -f
```

启动后访问：

- 服务地址：`http://<服务器IP>:8000`（未认证自动跳转 `/login` 输入口令）
- 浏览器入口：访问任意页面 → 跳转 `/login` → 输入口令 → 写入 Cookie → 跳转索引页
- API 文档：默认关闭（`DOCS_ENABLED=true` 开启后需认证访问 `/docs`）

**数据持久化**：`novels/` 目录通过卷挂载映射到容器内 `/app/novels`，小说文件与 Legado 阅读进度（`.legado_progress.json`）均保存在宿主机，重启或重建容器不会丢失。

**修改配置**：直接编辑 `.env` 后执行 `docker compose restart` 即可生效。若 `.env` 中口令为默认的 `qhapi-token`，容器首次启动会自动生成新口令并写回宿主 `.env`。

**代码变更后重建容器**（改了 Python/HTML/CSS/JS 源码后需重新构建镜像，因为 `COPY . .` 打包了源码）：

```bash
# 从当前代码重新构建镜像并重启容器
docker compose up -d --build

# 或分开执行（先构建，再重启）
docker compose build
docker compose up -d
```

**常用命令**：

```bash
docker compose down          # 停止并移除容器（数据保留在 ./novels）
docker compose down -v       # 慎用：同时删除卷数据
docker compose restart       # 修改配置后重启（仅 .env 变更）
docker compose up -d --build # 源码变更后重建镜像并启动
docker compose logs -f       # 查看日志
```

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
| `API_TOKEN` | `qhapi-token` | 通用 API 访问口令（留空则不验证；除 Legado 外所有接口需验证，支持 Bearer/Cookie，URL 无 token） |
| `DOCS_ENABLED` | `false` | Swagger 文档开关（默认关闭；开启后 /docs 需认证访问） |
| `LEGADO_ENABLED` | `true` | Legado HTTP API 整体开关（默认开；关闭后相关接口返回 403，永不验证 token） |
| `REMOTE_DOWNLOAD_ALLOW_INTRANET` | `false` | 是否允许远程下载内网地址的文件 |
| `UPLOAD_ENABLED` | `false` | 是否启用文件上传接口 |
| `UPLOAD_TIMEOUT_SECONDS` | `300` | 上传超时时间（秒） |
| `UPLOAD_CHUNK_SIZE_KB` | `512` | 分片上传每片大小（KB） |
| `FILE_DOWNLOAD_ENABLED` | `false` | 是否启用文件下载接口 |
| `FILE_RENAME_MODE` | `0` | 重命名模式：0=不重命名，1=小说名拼音，2=中文小说名，3=中文小说名-中文作者 |
| `FILE_RENAME_PINYIN` | `false` | 旧配置（兼容）：true 等价于 `FILE_RENAME_MODE=1` |
| `SOURCE_A_ENABLED` | `false` | 是否启用源A |
| `SOURCE_A_URL` | `""` | 源A URL |
| `SOURCE_B_ENABLED` | `false` | 是否启用源B |
| `SOURCE_B_URL` | `""` | 源B URL |
| `SOURCE_B_PATH` | `"/"` | 源B API 路径 |
| `MAX_FILE_SIZE_MB` | `50` | 单个文件大小上限（MB） |
| `DOWNLOAD_TIMEOUT_SECONDS` | `30` | 远程拉取下载超时（秒） |

### 3. 放入文本文件

将 `.txt` 或 `.md` 格式的文本文件放入 `novels/` 目录。

### 4. 启动服务

开发模式（热重载）：
```bash
# 独立执行
venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000

# systemd 服务已安装
systemctl restart qhapi

  # 查看状态
  systemctl status qhapi
  # 查看日志
  tail -f /var/log/qhapi/access.log
  tail -f /var/log/qhapi/error.log
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
curl -H "Authorization: Bearer 你的API_TOKEN" http://<服务器IP>:8000/docs
```

未配置 `API_TOKEN` 时直接访问 `/docs` 即可。

---

## Token 验证机制

配置 `API_TOKEN` 后，除 **Legado 接口**外的所有 API 与页面均需验证 token。

**Token 传递方式（任选其一）**：

| 通道 | 形式 | 适用场景 |
|------|------|---------|
| `Authorization` 头 | `Authorization: Bearer <token>` | 外部工具（curl/脚本）与浏览器 JS（推荐） |
| Cookie | `Cookie: qhapi_token=<token>` | 浏览器页面间跳转与表单提交（URL 干净） |
| 登录页 | `POST /login`（表单 token 字段） | 浏览器首次认证（写入 Cookie 后跳转索引页） |

> URL 查询参数 `?token=` 与路径入口 `/p/<token>` **均已移除**。浏览器访问任意受保护页面 → 自动跳转 `/login` 输入口令 → 写入 Cookie；外部工具使用 `Authorization: Bearer` 头。

**需验证 token 的接口**：

| 接口 | 说明 |
|------|------|
| `GET /api/v1/novels`（列表） | 列出文本文件 |
| `GET /api/v1/novels/{filename}/chapters` 等 | 章节列表 / 章节内容 / 内容读取 |
| `GET /api/v1/novels/files`（文件管理页） | 分页浏览、下载、删除、改名、改作者、一键重命名 |
| `GET /api/v1/novels/read`（阅读器页） | 在线阅读 |
| `GET /api/v1/novels/upload`、`/download`（页面） | 上传页 / 远程下载页 |
| `POST /api/v1/novels/upload*`（上传系列） | 单次/分片上传、取消（含 UUID 校验防路径穿越） |
| `POST /api/v1/novels/{filename}/delete` 等写接口 | 删除 / 隐藏 / 重命名 / 批量重命名 / 改作者 |
| `POST /api/v1/novels/download`（远程拉取） | 从 URL 下载 |
| `GET /api/v1/search*`、`/books/download` | 搜索 / 搜索页 / 书籍详情 / 下载书籍 |
| `GET /pages`、`/`、`/login`、`/docs`、`/openapi.json` | 页面入口、登录与文档 |

**不需要 token 的接口（Legado 外部协议）**：

| 接口 | 说明 |
|------|------|
| `GET /getBookshelf` | 书架列表（Legado App / VS Code 插件调用） |
| `GET /getChapterList` | 章节列表 |
| `GET /getBookContent` | 章节内容 |
| `POST /saveBookProgress`、`/saveBookProgressByChapter` | 保存阅读进度 |
| `GET /health` | 健康检查 |

> Legado 接口**永不验证 token**（保持外部工具兼容），只受 `LEGADO_ENABLED` 开关控制（默认开启）；关闭后返回 403「未开放」。
> 如 `API_TOKEN` 为空字符串，所有非 Legado 验证跳过。

### 登录与登出（浏览器）

| 接口 | 说明 |
|------|------|
| `GET /login` | 登录页（已登录自动跳转索引页） |
| `POST /login` | 提交口令（表单 `token` 字段），成功后写入 Cookie 并跳转 |
| `GET /logout` | 退出登录：清除 Cookie，跳转登录页 |

**浏览器使用流程**：
1. 访问任意受保护页面（或根路径 `/`）→ 自动跳转 `/login`
2. 输入口令 → 提交 → 写入 Cookie → 跳转索引页 `/api/v1/novels/pages`
3. 页面右上角 / 导航页左上角有退出按钮，点击后清除 Cookie 返回登录页

**外部工具（curl/脚本）**：使用 `Authorization: Bearer <token>` 头，无需登录流程。

---

## API 接口

| 方法 | 路径 | 功能 |
|------|------|------|
| `GET` | `/login` | 登录页（输入口令，写入 Cookie） |
| `POST` | `/login` | 登录提交（表单 token 字段，成功后跳转） |
| `GET` | `/logout` | 退出登录（清除 Cookie，跳转登录页） |
| `GET` | `/` | 根路径（未认证跳转 /login，已认证跳转索引页） |
| `GET` | `/api/v1/novels` | 列出所有文本文件（分页 + 扩展名过滤 + 作者） |
| `GET` | `/api/v1/novels/{filename}/chapters` | 获取文件的章节列表 |
| `GET` | `/api/v1/novels/{filename}/chapters/{chapter_number}` | 按章节获取内容（支持章节内偏移） |
| `GET` | `/api/v1/novels/{filename}/content` | 按全局偏移获取内容（支持按章节定位） |
| `POST` | `/api/v1/novels/download` | 远程拉取 URL 文件（需 REMOTE_DOWNLOAD_ENABLED=true） |
| `POST` | `/api/v1/novels/upload` | 上传本地文件（需 UPLOAD_ENABLED=true） |
| `POST` | `/api/v1/novels/upload/init` | 分片上传初始化 |
| `POST` | `/api/v1/novels/upload/chunk` | 分片上传数据块 |
| `POST` | `/api/v1/novels/upload/complete` | 分片上传完成 |
| `GET` | `/api/v1/novels/upload` | 浏览器访问的上传页面 |
| `GET` | `/api/v1/novels/pages` | 索引页（所有页面入口，需 token） |
| `GET` | `/api/v1/novels/read` | 文本阅读器（选书、翻页、设置，需 token） |
| `GET` | `/api/v1/novels/files` | 文件管理页面（分页浏览、下载、删除、改名、改作者、一键重命名，需 token） |
| `GET` | `/api/v1/novels/download` | 浏览器访问的远程下载页面 |
| `GET` | `/api/v1/novels/{filename}/download` | 下载服务器文件（需 FILE_DOWNLOAD_ENABLED=true） |
| `POST` | `/api/v1/novels/{filename}/delete` | 删除服务器文件（需 FILE_DOWNLOAD_ENABLED=true） |
| `POST` | `/api/v1/novels/{filename}/hide` | 隐藏/取消隐藏文件 |
| `POST` | `/api/v1/novels/{filename}/rename` | 重命名文件 |
| `POST` | `/api/v1/novels/batch-rename` | 按 `FILE_RENAME_MODE` 配置一键批量重命名所有未隐藏小说 |
| `POST` | `/api/v1/novels/{filename}/author` | 修改作者信息 |
| `GET` | `/api/v1/sources` | 列出可用搜索源 |
| `GET` | `/api/v1/search` | 搜索书籍（?q=关键词&source=txt/rar/auto） |
| `GET` | `/api/v1/search-page` | 浏览器搜索页面（搜索框+结果列表+一键下载） |
| `GET` | `/api/v1/book-detail` | 获取书籍详情和下载链接 |
| `GET` | `/health` | 健康检查 |

> **Token 验证说明**：如果配置了 `API_TOKEN`，上传/下载/远程拉取接口需传入匹配的 `token`（未配置或为空则跳过验证）。默认令牌首次启动时会自动生成并输出到控制台。

> **Swagger 文档**：默认关闭（`DOCS_ENABLED=true` 开启）；浏览器经 `/login` 认证后用 Cookie 访问 `/docs`；curl 加 `Authorization: Bearer` 头。

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

**搜索书籍（通过搜索源）：**
```bash
# 列出可用搜索源
curl http://localhost:8000/api/v1/sources

# 搜索
curl "http://localhost:8000/api/v1/search?q=关键词&source=txt"

# 浏览器搜索页面
# http://<服务器IP>:8000/api/v1/search-page

# CLI 搜索下载
bash scripts/qhapi_book.sh "关键词"
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
# 浏览器访问（经 /login 认证后 Cookie 自动携带，或直接访问）
# http://<服务器IP>:8000/api/v1/novels/files
```

**下载服务器文件到本地（需开启 FILE_DOWNLOAD_ENABLED=true）：**
```bash
# 浏览器直接访问（经 /login 认证后 Cookie 自动携带）
# http://<服务器IP>:8000/api/v1/novels/示例_江南烟雨.txt/download

# curl 下载（使用 Bearer 头）
curl -H "Authorization: Bearer 你的口令" -o output.txt "http://localhost:8000/api/v1/novels/%E7%A4%BA%E4%BE%8B_%E6%B1%9F%E5%8D%97%E7%83%9F%E9%9B%A8.txt/download"
```

## 功能特性

- **智能章节解析**：支持中文数字章节（第一章/第1章）、英文章节（Chapter 1）、数字序号、Markdown 标题等多种格式
- **自动编码检测**：使用 chardet 自动识别文件编码，支持 UTF-8、GBK、GB2312、BIG5 等
- **作者信息提取**：自动从书名（《书名》作者）、文件名、正文头部提取作者，支持手动修改并持久化
- **拼音重命名**：下载/上传后可自动将中文文件名转为拼音（FILE_RENAME_PINYIN=true）
- **路径穿越防护**：所有文件访问均做路径校验，确保安全
- **防同名覆盖**：下载文件时若文件名已存在，自动追加 `(1)`、`(2)` 等序号
- **下载大小限制**：通过配置限制单个下载文件的大小，防止资源滥用
- **分片上传**：大文件自动切分为多个小块分批传输，支持断点续传，避免超时失败
- **SSRF 防护**：远程下载仅允许公网地址（可配置允许内网）
- **阅读进度持久化**：阅读位置自动保存，重新打开继续阅读

---

## 📖 浏览器阅读器

访问 `/read`（或从索引页进入）打开在线阅读器，支持：

- **书架列表**：按最近阅读排序，显示进度与作者
- **自适应分页**：每页字数根据窗口大小和字号动态计算，无滚动条
- **翻页方式**：左右两侧悬浮按钮 + 全页边缘点击热区（上/左=上一页，下/右=下一页），章首/章尾自动跨章
- **阅读设置**：字号调节（12-32px）+ 5 种背景主题（护眼黄/纯白/暗黑/羊皮纸/墨绿），自动保存到 localStorage
- **章节目录弹窗**：点击 📑 打开，虚拟滚动（千章书仅渲染可视区节点，流畅不卡顿），自动定位当前章节，显示章节序号，支持输入章节号跳转
- **进度恢复**：关闭页面后重新打开，从上次位置继续阅读
- **移动端适配**：响应式布局、无滚动条、大点击热区，适合手机竖屏阅读

> 手机浏览器访问 `http://<服务器IP>:8000/login` 输入口令即可进入索引页，简单方便。

---

## 🔌 Legado HTTP API 兼容

本服务原生兼容 **Legado「阅读」App Web 服务协议**，可与 `yuedu_vscode_dicarbene` 等 VS Code 插件开箱即用。

### 兼容端点

| 方法 | 路径 | 参数 | 说明 |
|------|------|------|------|
| `GET` | `/getBookshelf` | `?page=1&page_size=20`（可选分页） | 获取书架（文件列表，含作者，page_size=0 全量） |
| `GET` | `/getChapterList` | `?url={bookUrl}` | 获取章节目录 |
| `GET` | `/getBookContent` | `?url={bookUrl}&index={n}` | 获取章节全文 |
| `POST` | `/saveBookProgress` | JSON Body | 保存阅读进度 |
| `POST` | `/saveBookProgressByChapter` | JSON Body | 按章节保存阅读进度 |

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
