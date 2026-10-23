# V1.5卡片与评论任务离线检查

- 日期：2026-10-22；代码：工作区未提交的V1.5增量。
- 环境：Windows、项目.venv、TemporaryDirectory隔离SQLite、进程内FastAPI TestClient；计数及Chat仅私有离线替身，release仍OFFLINE_READY。
- `python -m pytest backend/tests/guide/test_v15_cards.py -q -p no:cacheprovider`：当时10 passed／46.86秒，含正式答案创建新轮、程序阶段与暂缓、精确事实直接保存、并发／版本、源头变化明确ack、真实HTTP200／202。
- cards、execution、context、progress、counting、requirements foundation及service foundation联合：50 passed／188.29秒。更早V1.5全部已建专项91 passed／305.23秒为C06改动前基线，不是当前全量新结果。
- `python -m pytest backend/tests/guide/test_v15_comment_guides.py -q -p no:cacheprovider`：5 passed／26.33秒；真实评论目标、新RunReceipt／HTTP、评论锚点材料、候选创建不改正文、双版本／归档、原评论改变后重试拒绝。
- 前端相关59项通过／464.11毫秒；完整tsc通过，临时生产构建1248模块／544毫秒通过。后续C05增加后comment、cards、composer共15 passed／265.54毫秒，完整tsc通过，尚未重新生产构建。
- 修复：程序审计复用实际PHASE_CHANGED／DISCUSSION_UPDATED事件，reason_code=CARD_PROGRAM_ACTION；不新增未注册event_type。HTTP夹具修正真实HttpRuntime构造；SourceHead专项在执行中修改源码曾造成采样不一致，停止改动后重新执行通过。
- 产物：临时库、count journal及构建目录均在退出后清理；未留JSON、截图或原始日志。未启动／停止用户服务，未写用户库或执行Git写入，无真实模型／计数API、浏览器及供应方证据。
- 进行中：同轮progress新引用与卡片联动回归；后续结果追加，不提前标通过。候选采用／完成及新版请求详情仍待接入。
