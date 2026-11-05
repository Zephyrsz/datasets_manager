# 语音数据集 SQLite 管理

本项目采用“一个数据集注册表 + 每个数据集一张明细表”的结构。音频继续保存在原目录，数据库只保存元数据、音频文件名与字幕，不保存音频二进制。

## Web 管理界面

新增前后端分离的中文管理界面「声库」：

- 数据集库：搜索、排序、添加数据集、编辑存储配置，查看真实记录数及字幕覆盖率。
- 数据集明细：按文件名或字幕搜索、有无字幕筛选、每页 10 / 20 / 50 / 100 条分页；支持音频试听、单条字幕编辑和重新导入。
- 前端只调用 HTTP API；后端独立负责 SQLite 读写、源文件校验、音频文件读取与 Range 响应。
- 表单中的路径都指后端服务器上的文件。当前默认按本机单用户使用，不包含登录与多人权限功能。

### 安装与启动

Web 后端使用 Python 3.10+；前端使用 Node.js 20.19+ 或 22.12+。建议使用 Node.js 24 LTS。

```bash
cd /Users/rgwei/pj/pj_datasets
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cd frontend
npm ci
```

在两个终端分别启动：

```bash
# 终端 1：后端
cd /Users/rgwei/pj/pj_datasets
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

```bash
# 终端 2：前端
cd /Users/rgwei/pj/pj_datasets/frontend
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
| GET / POST | `/api/datasets` | 读取列表 / 注册并导入新数据集 |
| GET / PUT | `/api/datasets/{id}` | 数据集详情 / 保存完整配置 |
| POST | `/api/datasets/{id}/sync` | 按当前配置重新导入 |
| GET | `/api/datasets/{id}/records` | 分页搜索，支持 `page`、`page_size`、`q`、`subtitle=all/present/missing` |
| PATCH | `/api/datasets/{id}/records/{record_id}` | 保存字幕，JSON 为 `{"subtitle":"..."}`；空白或 `null` 清空字幕 |
| GET | `/api/datasets/{id}/records/{record_id}/audio` | WAV 文件响应，支持 Range 试听与定位 |

保存数据集配置与重新导入是两个独立操作。保存配置会验证源目录、字幕匹配和已登记音频是否完整，只更新元数据。手动字幕编辑只写入数据库，不改写原始清单。重新导入会以源字幕为准同步明细，因此界面要求确认覆盖行为。

API 接收的配置字段为 `name`、`storage_dir`、`audio_subdir`（默认 `wav`）、`transcript_path`（可为 `null`）。数据集 ID 自动分配。字幕文件仍使用本文下述 JSUT 格式。

### 验证

```bash
cd /Users/rgwei/pj/pj_datasets
.venv/bin/python -m unittest discover -s tests -v
cd frontend
npm run build
```

API 测试使用临时目录与独立 SQLite 文件，不修改当前已导入的语料。后端代码位于 `backend/`，前端位于 `frontend/`；原命令行导入工具继续可用。

## 已导入的数据

- 数据库：`/Users/rgwei/pj/pj_datasets/datasets.sqlite3`
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

`schema.sql` 是当前两张表的建表 SQL，可以在空数据库中创建相同结构，不包含数据。导入程序中的 SQL 定义负责动态创建后续的 `audio_dataset_2` 等表。

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
cd /Users/rgwei/pj/pj_datasets
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
| `schema.sql` | 当前两张表的实际建表结构 |
| `import_dataset.py` | 注册、校验、导入与重导工具 |
| `tests/test_import_dataset.py` | 使用临时目录和临时数据库的自动化测试 |

```bash
cd /Users/rgwei/pj/pj_datasets
.venv/bin/python -m unittest discover -s tests -v
sqlite3 datasets.sqlite3 'PRAGMA integrity_check;'
```

每个数据集独立明细表符合当前按数据集管理和查询的需求。以后若需要频繁跨数据集检索或统一统计，可以另行增加查询层，或者迁移为带 `dataset_id` 外键的统一明细表。
