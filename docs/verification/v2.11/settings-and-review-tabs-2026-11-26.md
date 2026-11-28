# WALL-E V2.11 代码设置与修改建议页签验证

2026-11-26（香港时间）。工作树 `codex/v211-receipt-followup`，基线 `fd484f4`。依据 [代码设置迭代](../../iterations/pending/v2.11/WALL-E.代码设置页签切换稳定性迭代_V_2.11.md) 和 [修改建议迭代](../../iterations/pending/v2.11/WALL-E.修改建议页签直接读取迭代_V_2.11.md)。

| 检查层次 | 操作与证据 | 实际结果 |
| --- | --- | --- |
| 旧版复现 | Edge，1680 px，`/settings/code?section=execution` 与需求 5 | 切到检查配置时滚动从 45 px 变成 0 px。后端设计文档直接打开修改建议显示「暂无修改建议」 |
| 前端离线 | `npm run format:check`、`node --test --test-reporter=tap tests/*.test.mjs`、`npm run build -- --configLoader runner --outDir ../../v211-code-settings-tab-qa/dist` | 格式、严格类型、658 项及构建通过。覆盖 API 路径、文档批次选择、旧请求取消、核对数据保留和历史导航。构建报告既有大资源警告 |
| 后端离线 | `python -m ruff format --no-cache --check backend/app`，先激活固定 SQLite 3.54.1，再执行 `pytest -q -p no:cacheprovider`，范围为 `test_openai_writes.py` 与 `test_v211_review_layout.py` | 621 个源码格式检查通过，11 项隔离回归通过。直接调用 pytest 的首轮因缺少固定 SQLite 激活而失败，改用固定运行时及明确临时目录后通过 |
| 线上 API | 发布后 `GET /api/v1/requirements/5/documents/17/pending-suggestion`、文档 8 同路由和需求 4 下文档 17 | 分别返回批次 4、空批次及 404。历史运行 53 的保存版本仍为修订 22 |
| 设置页签 | Edge，宽 1680 px 及窄 520 px，四分区轮换、前进后退和下拉 | 45 px 滚动保持，导航左坐标相同，公共核对卡片同一节点且加载属性零变化。实际浏览器为空核对列表 |
| 修改建议 | Edge，直接进入、切文档、回执、查询失败后重试、定位正文 | 后端设计文档直接读出 3 组 13 处，需求说明显示空态，回执按批次定位且未发起默认查询。隔离失败重试成功。定位首组后正文渲染出增删标记和选中高亮。页面脚本异常与业务写请求为零 |

8001 切换前无运行中 AI、代码或测试操作，已有 2 批待审阅。切换后唯一监听 PID 34436，沿用原数据库、Schema210、本地凭据文件和代理。新后端快照位于 `data/service-runtime-v211-review-20261125/source-tab-read-20261126`，旧快照 `source-initial-review-20261126` 保留。前端写入新静态资源后原子切换 `frontend-final/index.html`，主资源为 `assets/index-BbLC-R1M.js`，HTML SHA-256 为 `24100dad40530634801e1c386754ded89b9594379fc10812e63d8c8675063720`。回退入口保存在同一运行目录的 `frontend-tab-read-2026-11-26/previous-index.html`。

本轮线上检查未执行建议决定、配置写入、原请求恢复、模型或计数调用。发布使用工作区代码和部署快照，未提交或合并本轮变更。
