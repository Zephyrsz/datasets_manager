# 单音频注册 Implementation Plan

**Goal:** 工作空间的音频注册页支持互斥的原始长音频/参考音频登记与管理。
**Architecture:** 独立audio_assets表与AudioService，沿用DatasetService连接事务，FastAPI路由，React页面和原生抽屉。FFprobe仅在新增/编辑探测文件；列表只检查可用性。
**Spec:** docs/superpowers/specs/2026-11-05-single-audio-design.md
**Constraints:** 不自动登记用户录音；不删除源文件；保留未提交工作和已有数据集；本会话顺序实施，测试使用临时数据库。

- [x] tests/test_audio_assets.py先写HTTP行为测试，运行确认新入口不存在；PCM WAV与FFmpeg生成M4A用于验证真实格式。
- [x] backend/audio_service.py增加audio_assets建表、FFprobe校验、增改查删和路径唯一冲突；models.py增加AudioConfig互斥用途，main.py接入分页路由和Range文件响应。
- [x] 单音频测试通过，原54条回归通过。
- [x] frontend/src/AudioLibrary.tsx实现列表/搜索/用途/分页/空错误状态和登记编辑抽屉；api.ts增加类型；App.tsx接入工作空间导航和共享播放器；styles.css扩展响应式。
- [x] README/PRODUCT/schema.sql补充真实接口、字段及FFprobe依赖说明；npm run build通过。
- [x] 临时服务和数据库中完成桌面/移动交互验收，独立审查修复后回归；git diff --check，正式数据保全，交付。

## 验证结果

- 新增16条单音频HTTP集成测试全部通过，完整70条测试通过。先验证入口404和删除ID复用用例失败，再实现并通过。
- TypeScript和Vite生产构建通过；界面机械检查返回空问题列表。
- 浏览器临时数据库验收：分别登记source/reference、编辑及重开确认文本持久化、用途单选、分类筛选、搜索空状态、WAV试听readyState=4。1440px桌面与390px移动端无横向溢出，移动端可通过工作空间导航切页。
- 独立审查发现SQLite复用删除ID的问题，已改AUTOINCREMENT并添加回归，复查无剩余阻塞。
- 正式服务已按原端口8000/15173重启；新音频表为空。正式库已备份至`.run/audio-qa/before-single-audio.sqlite3`，原注册表和5000条语料记录的逻辑校验值与升级前一致，integrity_check=ok。
- 原有.gitignore、前端代理配置、start.sh及其测试保持原始SHA-256；既有未提交修改保留。
- 本轮不注册真实录音、不运行模型。探测仅验证可读取元信息，后续模型仍须验证音质、时长与参考文本需求。
