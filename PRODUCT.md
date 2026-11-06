# 语音数据集管理

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

管理本地语音语料的数据使用者；当前已有 JSUT basic5000 的 5,000 条真实记录。

## Product Purpose

注册和配置语音数据集，从数据集列表进入音频与字幕明细；另行登记单个原始音频和参考音频，供后续处理及语音克隆使用。后端负责 SQLite 读写，前端通过 API 操作。

## Capabilities and Constraints

保留 audio_datasets 注册表、audio_dataset_<id> 独立明细表和源音频目录。支持添加、配置、重新导入、分页、搜索、音频试听、字幕编辑。不改写原始音频或字幕清单。

单音频处理模块完成导出后，可通过 CLI 或 HTTP 登记最终 PCM WAV 与 UTF-8 字幕清单。首次登记原子写入；相同配置与文件名集合重复登记复用 ID，并保留人工修改或清空的字幕。登记前校验音文对应、WAV 完整性及目录边界；不保存原始长音频或处理流程日志，不比较文件内容版本。原有显式重新导入仍以源字幕为准。

工作空间增加「音频注册」。独立 audio_assets 表登记本机单文件路径，每条只选一种用途：原始长音频或参考音频；参考文本、语言、说话人和备注选填。支持 M4A/WAV 等常见格式、分页搜索/分类/试听/编辑/移除索引。元信息由 FFprobe 在保存时探测；不复制或删除音频，文件丢失保留登记供修复。处理进度仍由 voice_tools 本地记录，注册页不执行 ASR 或 TTS。

## Stack

本轮实施默认：React + TypeScript + Vite 前端，FastAPI + SQLite 后端。用户明确要求前后端分离，未指定框架。

## Operating Context

实施假设：本机单用户工具，默认仅监听 127.0.0.1。路径均指后端服务器上的文件，不是浏览器所在机器。多人账户、远程部署和权限管理未纳入本轮。

## Evidence on Hand

datasets.sqlite3、import_dataset.py、schema.sql 和真实 basic5000 音频及字幕。

## Product Principles

真实数据驱动页面；错误不隐藏；配置保存与源文件重新导入分开；不自动删除源文件或已有记录。
