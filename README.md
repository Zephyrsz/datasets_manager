# 语音数据集 SQLite 管理

本项目采用“一个数据集注册表 + 每个数据集一张明细表”的结构。音频继续保存在原目录，数据库只保存元数据、音频文件名与字幕，不保存音频二进制。

## Web 管理界面

新增前后端分离的中文管理界面「声库」：

- 数据集库：搜索、排序、添加数据集、编辑存储配置，查看真实记录数及字幕覆盖率。
- 音频注册：单独登记原始长音频或参考音频，配置文件路径、用途、参考文本等信息，支持搜索、分类、试听、编辑与移除登记。
- 数据集明细：按文件名或字幕搜索、有无字幕筛选、每页 10 / 20 / 50 / 100 条分页；支持音频试听、单条字幕编辑和重新导入。
- 前端只调用 HTTP API；后端独立负责 SQLite 读写、源文件校验、音频文件读取与 Range 响应。
- 表单中的路径都指后端服务器上的文件。当前默认按本机单用户使用，不包含登录与多人权限功能。

### 安装与启动

Web 后端使用 Python 3.10+；前端使用 Node.js 20.19+ 或 22.12+。建议使用 Node.js 24 LTS。

推荐在项目根目录使用统一管理脚本；也可以从其他目录通过脚本的完整路径执行：

```bash
./start.sh start     # 后台启动前后端；不传参数时也默认执行 start
./start.sh status    # 查看状态；未全部运行时返回非零状态码
./start.sh stop      # 停止前后端及其子进程
./start.sh restart   # 重启整体服务
```

首次 `start` 会自动创建 `.venv`、按 `requirements.lock` 安装后端依赖，并在缺少前端依赖时执行 `npm ci`，需要网络连接。后续启动复用已有依赖。脚本等待后端健康检查和前端 HTTP 响应后才报告启动成功；重复启动不会创建多份服务。启动失败会清理本次新启动的服务，`stop` 只处理本脚本记录且身份匹配的进程。`stop`、`status` 不需要安装应用依赖。

进程记录位于 `.run/`，追加日志位于 `.logs/backend.log`、`.logs/frontend.log`；两者均已加入 Git 忽略。查看日志：

```bash
tail -f .logs/backend.log .logs/frontend.log
```

端口默认仍为后端 `8000`、前端 `5173`。端口被占用时会明确报错，可按需调整；脚本会同步设置前端 API 代理及后端默认允许来源：

```bash
BACKEND_PORT=18000 FRONTEND_PORT=15173 ./start.sh start
BACKEND_PORT=18000 FRONTEND_PORT=15173 ./start.sh restart
./start.sh stop
```

修改端口后，后续 `start`、`restart` 需使用相同的环境变量；`stop`、`status` 按进程记录定位，无需重复传入端口。可通过 `PYTHON_BIN` 指定创建虚拟环境的 Python，通过 `START_TIMEOUT`、`STOP_TIMEOUT` 调整各服务启动和停止的等待秒数（默认分别为 30、10）。已有的 `DATASETS_DB`、`FRONTEND_ORIGINS`、`VITE_API_BASE` 环境变量仍可使用。脚本沿用本机开发模式，默认只监听 `127.0.0.1`。

如需手动安装依赖和分别启动，也可使用以下命令：

```bash
cd /path/to/datasets_manager
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cd frontend
npm ci
```

在两个终端分别启动：

```bash
# 终端 1：后端
cd /path/to/datasets_manager
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

```bash
# 终端 2：前端
cd /path/to/datasets_manager/frontend
npm run dev
```

前端地址：`http://127.0.0.1:5173`；交互式 API 文档：`http://127.0.0.1:8000/docs`。

默认打开已有的 `datasets.sqlite3`，启动服务不会自动重新导入数据。前端开发服务器将 `/api` 请求代理到后端；构建静态前端使用 `npm run build`。本机可用 `npm run preview` 验证构建产物；部署时由 Web 服务器托管 `frontend/dist`，将 `/api` 反向代理到 FastAPI，并为前端路径配置 SPA 回退到 `index.html`。

可配置环境变量：

- `DATASETS_DB`：后端 SQLite 文件路径，默认项目根目录的 `datasets.sqlite3`。
- `FRONTEND_ORIGINS`：允许写入请求的浏览器来源，英文逗号分隔；默认 `http://127.0.0.1:5173,http://localhost:5173`。
- `VITE_API_BASE`：前端 API 基址，默认 `/api`；独立域名部署时在前端构建前设置，例如 `http://127.0.0.1:8000/api`。

### API

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| GET | `/api/health` | 后端与数据库连接检查 |
| GET / POST | `/api/audios` | 分页搜索单音频登记 / 注册一个本机音频 |
| GET / PUT / DELETE | `/api/audios/{id}` | 单音频详情 / 完整更新配置 / 仅移除登记 |
| GET | `/api/audios/{id}/file` | 读取已登记音频，支持 Range 试听 |
| GET / POST | `/api/datasets` | 读取列表 / 注册并导入新数据集 |
| POST | `/api/datasets/register` | 登记处理完成的 WAV 与字幕；支持保留人工字幕的重复调用 |
| GET / PUT | `/api/datasets/{id}` | 数据集详情 / 保存完整配置 |
| POST | `/api/datasets/{id}/sync` | 按当前配置重新导入 |
| GET | `/api/datasets/{id}/records` | 分页搜索，支持 `page`、`page_size`、`q`、`subtitle=all/present/missing` |
| PATCH | `/api/datasets/{id}/records/{record_id}` | 保存字幕，JSON 为 `{"subtitle":"..."}`；空白或 `null` 清空字幕 |
| GET | `/api/datasets/{id}/records/{record_id}/audio` | WAV 文件响应，支持 Range 试听与定位 |

保存数据集配置与重新导入是两个独立操作。保存配置会验证源目录、字幕匹配和已登记音频是否完整，只更新元数据。手动字幕编辑只写入数据库，不改写原始清单。重新导入会以源字幕为准同步明细，因此界面要求确认覆盖行为。

迁移数据集时，只修改根目录即可：如果字幕清单原本位于旧根目录内，且没有单独修改字幕清单字段，保存时会保留其相对位置并迁移到新根目录。位于数据集根目录之外的字幕清单、或显式指定的新字幕路径会保持用户指定的位置。新目录或迁移后的字幕清单无效时，原配置保留；保存配置不会重新导入或覆盖已有字幕。

API 接收的配置字段为 `name`、`storage_dir`、`audio_subdir`（默认 `wav`）、`transcript_path`（普通创建接口可为 `null`）。数据集 ID 自动分配。字幕文件仍使用本文下述 JSUT 格式；结果登记接口必须有字幕，规则如下。

### 单音频处理结果登记

voice_tools 每次处理一个输入音频，完整导出最终结果后调用此入口。输入信息、ASR/对齐/分句结果、进度与错误仍保存在处理项目的本地日志或 JSON 中。管理器只登记最终 WAV 和字幕，复用现有注册表、明细表和界面，无需数据库迁移。

最终目录示例：

```text
dataset/
  wav/
    000001.wav
    000002.wav
  transcript_utf8.txt
  logs/process.jsonl       # 可选；管理器不读取
```

`transcript_utf8.txt` 使用 UTF-8（可带 BOM），每行 `文件名去扩展名:字幕`：

```text
000001:日本語の字幕。
000002:時刻は12:34です。
```

文件必须全部导出完成再登记。入口要求每个 WAV 都有一条非空字幕，且没有多余字幕；不递归扫描。它会完整分块读取 PCM WAV，拒绝空音频、无法解析或截断的 WAV。字幕必须位于数据集根目录内，音频必须位于指定的音频目录内，符号链接也遵守此限制。其他格式需要由处理模块先导出为 PCM WAV。附属 SRT、TXT、JSON 和日志不参与导入。

命令行入口只依赖 Python 3.9+ 标准库，不要求启动 Web 服务。以下输出目录为示意，需替换成实际已完成的目录：

```bash
python3 /Users/rgwei/pj/pj_data/datasets_manager/register_result.py \
  --name '20261028井上和-sentences-v1' \
  --root '/绝对路径/最终数据集目录'
```

`--audio-subdir` 默认 `wav`，`--transcript` 默认 `transcript_utf8.txt` 且不可省略为无字幕结果。`--db` 默认脚本所在目录的 `datasets.sqlite3`；如果后端配置了 `DATASETS_DB`，命令行需用 `--db` 指向同一文件。成功时标准输出为 JSON，含 `dataset_id`、`registration_status` 和记录计数；失败时返回非零状态码，错误写入标准错误输出。

处理程序也可以调用 `POST /api/datasets/register`：

```bash
curl --fail-with-body http://127.0.0.1:8000/api/datasets/register \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "20261028井上和-sentences-v1",
    "storage_dir": "/绝对路径/最终数据集目录",
    "audio_subdir": "wav",
    "transcript_path": "transcript_utf8.txt"
  }'
```

路径由后端所在机器解析，`storage_dir` 必须为绝对路径。HTTP 响应包含 `status`、`dataset`（现有数据集详情）和 `import_result`（导入计数及 `registration_status`）：

| 情况 | HTTP 状态 | 结果 |
| --- | --- | --- |
| 首次登记 | 201 | `status="created"`，自动分配数据集 ID，原子写入全部记录 |
| 相同登记重试 | 200 | `status="existing"`，复用数据集与样本 ID，保留数据库中的人工字幕，包括已清空的字幕 |
| 名称、目录、配置或音频文件名集合冲突 | 409 | 保留已有登记与记录 |
| 文件缺失、音文不匹配、坏 WAV 或路径不合法 | 400 | 不写入新登记或部分记录 |
| 请求字段不合法，例如字幕路径为 `null` 或空白 | 422 | 请求被拒绝 |

相同登记指规范化后的名称、根目录、音频子目录、字幕路径相同，且完整音频文件名集合相同。它不比较音频或字幕的内容指纹，也不判断句子语义是否完整。登记后应保持该目录的文件不变；重新生成不同内容时使用新名称和新目录。管理器引用这些文件，不复制或移动文件。

此入口可以在响应丢失后安全重试，也支持并发重复登记。**重复登记不会同步源字幕**；确实需要用清单覆盖数据库字幕时，仍需显式调用原导入器或 `/api/datasets/{id}/sync`。原 `POST /api/datasets` 继续对重复名称或目录返回 409。登记完成后刷新现有数据集列表，即可查询、试听和编辑字幕。

### 单个原始音频与参考音频注册

在工作空间选择「音频注册」，点击「注册音频」，填写名称、音频文件的绝对路径，并选择一种用途：

- **原始长音频**（`source`）：保存待转写、分句或制作数据集的输入文件。
- **参考音频**（`reference`）：供语音克隆或 TTS 使用，可选填写说话人、语言和音频实际说出的文本；是否必须有参考文本、适合多长的音频由后续模型决定，登记页不强制。

每条音频只能有一种用途；同一规范化路径只能登记一次，可编辑已有登记修改用途和配置。名称可以重复。登记保存在同一 SQLite 文件中的独立 `audio_assets` 表，与目录型数据集分开管理。后端首次启动自动创建新表和用途索引，不迁移或改写已有数据集记录。

此功能新增系统依赖 **FFmpeg / ffprobe**。macOS 可使用 `brew install ffmpeg`；后端运行环境的 PATH 中需要有 `ffprobe`。缺少时新增/编辑返回 503，列表和已有数据集功能仍可使用。支持 WAV、M4A、MP3、FLAC、OGG、OPUS、AAC、WebM、AIFF。新增和编辑时探测有效音轨、时长、大小、采样率、声道和编码，超时 20 秒返回可重试错误；不会逐帧完整解码长音频，也不保证录音质量或参考音色适合某个模型。试听能力取决于浏览器的格式支持。

文件始终保留在原位置；不上传、复制或移动。移除登记仅删除索引，原文件保留。文件被移动或丢失时登记仍可查看，显示不可用，可编辑路径修复；已登记路径变成指向其他文件的符号链接时停止提供试听，需要重新编辑确认。

供处理模块或 TTS 调用方使用的请求示例（文件路径为示意，需替换）：

```bash
curl --fail-with-body http://127.0.0.1:8000/api/audios \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "访谈原始录音",
    "file_path": "/绝对路径/recording.m4a",
    "kind": "source",
    "notes": "待转写与切句"
  }'
```

参考音频使用 `kind="reference"`，可额外提供 `speaker`、`language`、`reference_text` 和 `notes`，均允许省略或为空。成功返回 201 和音频对象，包含稳定 `id`、配置、探测元信息、创建/更新时间与实时 `file_available`。已移除的音频 ID 不会被重新分配，后续查询旧 ID 返回 404。重复路径返回 409，文件不合法返回 400，用途或必填字段非法返回 422。更新使用 `PUT /api/audios/{id}`，提交完整配置；省略可选字段会将它们清空。

`GET /api/audios?kind=reference&page=1&page_size=20&q=说话人` 返回 `{items,total,page,page_size}`；`kind` 可选 `all/source/reference`，按登记 ID 倒序分页，支持名称、路径、说话人或参考文本搜索。`GET /api/audios/{id}` 可取得路径和参考文本，供后续处理模块调用。元信息为最近一次保存时的探测结果，外部改写文件后需重新保存配置刷新。注册动作不运行 ASR、切句或克隆模型。

### 验证

```bash
cd /Users/rgwei/pj/pj_data/datasets_manager
.venv/bin/python -m unittest discover -s tests -v
cd frontend
npm run build
```

API 测试使用临时目录与独立 SQLite 文件，不修改当前已导入的语料。后端代码位于 `backend/`，前端位于 `frontend/`；原命令行导入工具继续可用。

## 已导入的数据

- 数据库：`/Users/rgwei/pj/pj_data/datasets_manager/datasets.sqlite3`
- 数据集名称：`basic5000`
- 数据集 ID：`1`
- 根目录：`/Users/rgwei/pj/train_datasets/jp_audio/jsut_ver1.1/basic5000`
- 音频子目录：`wav`
- 字幕清单：根目录下的 `transcript_utf8.txt`
- 明细表：`audio_dataset_1`，共 5,000 条，字幕全部非空。

## 表结构

### 注册表 `audio_datasets`

| 字段 | SQLite 类型 | 含义 |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | 正整数数据集 ID；可指定，也可自动分配 |
| `name` | TEXT NOT NULL UNIQUE | 数据集名称，不允许空白；不同语料的同名子集可用 `语料/子集` 命名 |
| `storage_dir` | TEXT NOT NULL UNIQUE | 数据集根目录，存为规范化绝对路径 |
| `audio_subdir` | TEXT NOT NULL | 根目录下的音频相对目录，默认 `wav`；音频直接位于根目录时使用 `.` |
| `transcript_path` | TEXT NULL | 字幕清单的绝对路径；没有字幕文件时为 SQL `NULL` |
| `created_at` | TEXT NOT NULL | 注册时间，UTC，ISO 8601 格式 |

同一目录只注册一次。明细表名称由 `audio_dataset_` 与数据集 ID 拼接，避免额外保存可推导字段。

### 明细表 `audio_dataset_<id>`

| 字段 | SQLite 类型 | 含义 |
| --- | --- | --- |
| `id` | INTEGER PRIMARY KEY | 表内记录 ID；首次导入按音频文件名排序分配，重导保留已有 ID |
| `subtitle` | TEXT NULL | 对应音频的原始字幕；没有字幕时为 SQL `NULL` |
| `audio_name` | TEXT NOT NULL UNIQUE | 含扩展名的音频文件名，例如 `BASIC5000_0001.wav` |

`audio_name` 不允许包含路径分隔符。完整音频路径按下式得到：

```text
storage_dir / audio_subdir / audio_name

/Users/rgwei/pj/train_datasets/jp_audio/jsut_ver1.1/basic5000/wav/BASIC5000_0001.wav
```

每张明细表只属于一个数据集，因此不重复保存 `dataset_id`。注册 ID 与表名之间的对应关系由导入程序在同一事务中维护，不是 SQL 外键；不要单独删除注册行或重命名明细表。

`schema.sql` 包含数据集注册表、示例明细表及单音频登记表的建表 SQL，可以在空数据库中创建相同结构，不包含数据。导入程序中的 SQL 定义负责动态创建后续的 `audio_dataset_2` 等表。单音频表由后端启动时独立创建。

## 查询示例

```sql
-- 查看所有已注册的数据集及其明细表名。
SELECT *, 'audio_dataset_' || id AS detail_table
FROM audio_datasets;

-- 查询 basic5000，并拼出音频完整路径。
SELECT
    a.id,
    a.subtitle,
    a.audio_name,
    d.storage_dir || '/' || d.audio_subdir || '/' || a.audio_name AS audio_path
FROM audio_dataset_1 AS a
CROSS JOIN audio_datasets AS d
WHERE d.id = 1
ORDER BY a.id
LIMIT 10;

-- 统计总记录数与非空字幕数。
SELECT count(*) AS total, count(subtitle) AS with_subtitle
FROM audio_dataset_1;
```

程序中使用 `pathlib.Path(storage_dir) / audio_subdir / audio_name` 拼接路径。SQL 表名不能使用 `?` 参数占位符；动态访问明细表时，只能由经过验证的正整数数据集 ID 生成表名，字段值仍使用参数绑定。

## 导入与重复执行

依赖 Python 3.9+ 与 SQLite 3.24+，全部使用标准库，无需安装第三方包。

```bash
cd /Users/rgwei/pj/pj_data/datasets_manager
python3 import_dataset.py \
  --db datasets.sqlite3 \
  --dataset-id 1 \
  --name basic5000 \
  --root /Users/rgwei/pj/train_datasets/jp_audio/jsut_ver1.1/basic5000 \
  --transcript transcript_utf8.txt
```

- `--db` 可省略，默认使用脚本所在目录下的 `datasets.sqlite3`。
- `--dataset-id` 可省略：已注册的数据集复用原 ID，新数据集自动分配 ID。
- `--transcript` 可省略：注册表的 `transcript_path` 和所有明细的 `subtitle` 均存为 `NULL`。省略后不会自动探测同名清单。
- 字幕文件支持 UTF-8 / UTF-8 BOM，每个非空行格式为 `音频文件名（不含扩展名）:字幕`；仅按第一个英文冒号切分，保留字幕中的冒号。
- 当前导入器扫描 `--audio-subdir` 指定目录中的全部 WAV 文件，不递归扫描，扩展名大小写均可；其他格式或其他字幕格式需要扩展适配器。
- 提供字幕清单时，要求音频与字幕一一对应。重复字幕标识、缺失字幕、找不到对应音频的字幕、格式错误都会使整次导入失败。
- 同名或同目录注册的元数据必须与已有值一致，否则拒绝导入，避免错误覆盖。需要迁移目录或增加字幕来源时，先显式调整注册元数据。
- 重复导入根据唯一的 `audio_name` 添加新记录、更新变化的字幕，不重复插入，也不改变已有 ID。
- 不自动删除记录；如果数据库中已登记的音频在源目录中消失，则拒绝导入，保留原记录。
- 注册、建明细表和写入记录在同一个事务中完成；中途发生错误会回滚。源音频和字幕文件始终只读。

## 文件与验证

| 文件 | 用途 |
| --- | --- |
| `datasets.sqlite3` | 已导入 basic5000 的数据库 |
| `schema.sql` | 数据集注册/示例明细及单音频登记的建表结构 |
| `backend/audio_service.py` | 单音频元信息探测、路径登记、管理和试听文件定位 |
| `import_dataset.py` | 注册、校验、导入与重导工具 |
| `register_result.py` | 最终 PCM WAV 与字幕校验、首次登记及保留人工字幕的重复登记 |
| `tests/test_import_dataset.py` | 使用临时目录和临时数据库的自动化测试 |
| `tests/test_register_result.py`、`tests/test_result_registration_api.py` | 结果登记、并发重试、文件校验、HTTP 与现有查询/试听兼容性测试 |
| `tests/test_audio_assets.py` | 单音频分类、增改查删、M4A/Range、持久化与数据集兼容测试 |

```bash
cd /Users/rgwei/pj/pj_data/datasets_manager
.venv/bin/python -m unittest discover -s tests -v
sqlite3 datasets.sqlite3 'PRAGMA integrity_check;'
```

每个数据集独立明细表符合当前按数据集管理和查询的需求。以后若需要频繁跨数据集检索或统一统计，可以另行增加查询层，或者迁移为带 `dataset_id` 外键的统一明细表。
