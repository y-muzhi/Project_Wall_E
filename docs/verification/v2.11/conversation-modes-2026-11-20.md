# V2.11 AI 对话双状态验证（2026-11-20）

- 范围：Windows 本地工作区，`a0f4059` 基线上叠加 V2.11 改动；5174 前端代理既有 8001 后端。
- 前端：`npm run format:check`、`npm run typecheck` 通过；`npm test` 577 项通过。覆盖草稿保留、先选范围再发送、按章节与整篇发送、载入依据期间切换、未知结果的原操作重放、讨论版本变化拦截、主题冲突和重新读取，以及既有建议审阅。
- 构建：运行 Vite `build({build:{write:false,reportCompressedSize:false}})`，内存构建通过，确认产物包含写入状态及主题选择。现有 `dist` 未覆盖。
- 后端离线范围：`.venv/Scripts/python.exe -B -X utf8 -m unittest backend.tests.documents.test_scopes` 5 项通过，覆盖章节边界、只读请求无写入范围、错误定位拒绝。另尝试 `test_v15_local_revision.py::test_section_local_output_inserts_inside_and_preserves_identical_outside_blocks_by_frozen_position` 和 `test_v15_discussion.py::test_document_focus_and_removed_commands_preserve_business_status`。隔离 pytest 收集 2 项后首项长时间未返回，已取消；有网络及业务库读取保护的复跑表现相同。本轮相关临时目录未残留，两项事务检查未取得结果。
- 现场：确认 5174 实际返回更新后的输入组件、对话控制、详情页、主题对象及样式。需求 #2 默认讨论，打开主题显示「暂无讨论主题」。写入范围含整篇和真实章节，选择第一章后可移至第二章。484 和 306 像素的输入区均可操作，窄区两按钮同行；切到进展再返回仍保留写入状态及第二章。切回讨论后范围隐藏，正文仍为 V2。前端 94200、后端 58436 保持运行。
- 实际页面仅进行只读交互。未触发用户文档写入和模型或计数调用；真实供应方表现不在本次检查范围内。
