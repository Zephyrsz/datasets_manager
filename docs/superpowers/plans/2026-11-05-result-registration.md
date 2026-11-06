# 最终音频与字幕结果登记 Implementation Plan

> 执行方式：用户已确认实施，在当前会话内顺序完成；保留工作区已有的启动脚本、前端代理和文档修改，不提交或迁移这些修改。

**Goal:** 为单音频处理完成后的WAV与字幕目录提供可安全重复调用的登记入口，复用现有数据库和界面。

**Architecture:** 沿用`audio_datasets`与`audio_dataset_<id>`。在现有事务导入器增加显式的“复用已有登记而不更新记录”策略；新的结果登记模块校验PCM WAV与一一对应的字幕，HTTP和CLI共享此逻辑。处理日志、原始音频信息和时间戳仍由voice_tools本地保存。

**Tech Stack:** Python标准库、SQLite、现有FastAPI/Pydantic；不新增运行依赖，不改前端布局。

**Spec:** `/Users/rgwei/pj/pj_audio/voice_tools/docs/soniqo-sentence-segmentation-research.md` 第13节及本次用户确认；下述安全重复登记是本次管理器最小扩展。

## Global Constraints

- 不增加音源库、任务/批次/来源关系表，不处理ASR或LLM日志。
- 只读取最终源文件；真实`datasets.sqlite3`不参与测试或样例登记。
- 输出目录包含`wav/`与UTF-8 `transcript_utf8.txt`；每行`文件名去扩展名:字幕`。
- 现有`import_dataset.py`及`POST /api/datasets`保留显式更新/重复冲突行为；新登记入口不隐式调用sync。
- 重复登记按规范化配置和完整音频文件名集合识别；不声称具有文件内容版本鉴定能力。内容变化应使用新目录和新名称。

## Task 1: 标准库结果登记模块与CLI

**Files:** 新建`register_result.py`、`tests/test_register_result.py`；修改`import_dataset.py`。

**Interfaces:**

```python
def import_dataset(*, db, name, root, audio_subdir="wav", transcript=None,
                   dataset_id=None, on_existing="update", validate_source=None) -> dict: ...

def register_result(*, db, name, root, audio_subdir="wav",
                    transcript="transcript_utf8.txt") -> dict: ...
```

`on_existing="reuse"`在同一个`BEGIN IMMEDIATE`事务中检查配置与文件名集合。相同登记直接返回计数和`registration_status="existing"`，不执行字幕或记录更新；新增结果返回`registration_status="created"`。配置或样本集合冲突使用`RegistrationConflict(ValueError)`。

登记模块通过`validate_source`校验导入器唯一一次扫描的快照，校验后不重扫并接纳新文件。RIFF数据块长度另行校验，避免`wave.getnframes()`向下取整漏掉半帧。文件发布后仍需保持不变；文件系统与SQLite不声称跨介质原子性。

- [x] 先写可运行的集成测试：临时PCM WAV/字幕导入、人工改字后重复登记、并发登记、冲突不写入、坏WAV/截断WAV/零样本/缺字幕/路径逃逸拒绝、CLI返回JSON与非零错误退出。
- [x] 用`.venv/bin/python -m unittest discover -s tests -p test_register_result.py -v`观察新行为失败；模块缺失先以CLI行为测试失败确认入口不存在。
- [x] 新增事务策略，仅对`reuse`分支不写既有记录；原`update`分支保留。
- [x] 实现`register_result()`：规范化输入，使用现有`read_source`校验音文对应，拒绝音频/字幕越出根目录，分块完整读取PCM帧以检测空文件或截断；最后调用事务导入器的reuse策略。
- [x] CLI使用`--name --root --db --audio-subdir --transcript`；默认字幕名固定，输出导入结果JSON，不创建本地处理日志。
- [x] 运行新增测试和原`test_import_dataset.py`，确认旧的重导更新行为保持。新增14条CLI/共享模块测试及原9条导入器测试通过。

## Task 2: 结果登记HTTP入口

**Files:** 修改`backend/models.py`、`backend/main.py`、`backend/service.py`，新建`tests/test_result_registration_api.py`。

**Interfaces:** `POST /api/datasets/register`接收已有配置字段，字幕默认`transcript_utf8.txt`且不允许NULL/空白。返回`{status,dataset,import_result}`，新登记201、复用200、配置/文件名集合冲突409、非法文件400、请求字段非法422。

HTTP委托共享标准库模块；值错误沿用现有异常处理。重复调用不覆盖数据库人工字幕。既有`POST /api/datasets`仍对重复请求返回409。

- [x] 先写API测试，在尚未增加路由时验证请求失败；测试覆盖默认文件名、可重复请求、人工字幕保留、来源限制和错误不留登记。
- [x] 实现请求模型、服务方法及路由。服务方法只把明确的登记冲突转为409，不把格式错误吞成成功。
- [x] 运行新API测试与旧`test_api.py`；确认已登记结果能用既有明细查询和音频Range试听。新增11条API测试及原13条API测试通过。

## Task 3: 文档、验证与交付

**Files:** 更新`README.md`、`PRODUCT.md`及voice_tools调研第13节，保留原文档中无关的启动脚本修改。

- [x] 写清结果目录、HTTP和CLI用法、`created/existing`响应、重试与显式sync区别，以及不比较文件内容版本的限制。
- [x] 执行`.venv/bin/python -m unittest discover -s tests -v`与`npm run build`。测试只使用临时数据库。
- [x] 检查本次差异、数据库/schema与原有未提交文件散列，确认没有写入真实语料。
- [x] 回读更新的接口和说明，交付可复制的调用命令和实际测试结果。

## 执行结果（2026-11-05）

- 完整测试：54条通过，其中本次新增25条（CLI/共享模块14条、HTTP11条），保留原29条回归测试。
- 前端：`npm run build`通过，TypeScript检查和Vite生产构建成功。
- `git diff --check`通过。正式`datasets.sqlite3`、`schema.sql`、原有`.gitignore`、前端代理配置、`start.sh`与启动脚本测试的SHA-256均与实施前一致。
- 独立审查发现并修复两处校验缺口：半帧/截断RIFF被误收，以及校验后第二次扫描接纳新文件。均先复现失败，再通过回归测试；独立复查确认无剩余阻塞项。
- 全量测试中有既有Starlette/httpx弃用提示和旧导入器测试的SQLite连接资源提示；本次新增测试显式关闭连接，未新增运行依赖。
- 最终结果目录必须先完整发布并保持文件不变；登记不承担内容版本鉴定或跨文件系统/SQLite的原子发布。
