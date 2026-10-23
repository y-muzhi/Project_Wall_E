# AI 请求上下文与用量展示专项验证

日期：2026-10-11。对应 UX-032／OBS-001。范围：两个只读接口、摘要／详情及运行记录复用、原业务展示的相关回归。没有调用真实模型、重新计数、代提交答案或编辑用户正文。

## 1. 离线检查

- 后端组合：`.venv/Scripts/python.exe -X utf8 -m unittest backend.tests.guide.test_model_calls.ModelCallReadTests backend.tests.guide.test_confirmed_response backend.tests.guide.test_response_display backend.tests.shared.test_http_cards backend.tests.shared.test_http_guide_status`，31 项通过。新 7 项覆盖小摘要／未知用量、真实 0／缓存、全部尝试、快照与后续正文独立、旧记录缺字段及非 JSON 输入、程序回执／失败／取消／准备中、HTTP 边界及只读无变化。原确认写入、卡片和模型返回展示相关检查通过。
- 前端：`node --test tests/model-calls.test.mjs tests/cards.test.mjs tests/api-models.test.mjs tests/ai-read-owner.test.mjs`，49 项通过，其中新专项 5 项。覆盖缓存不重复计入、缺失字段、摘要不加载详情、相同运行并发合并、隐藏／退出迟到、失败保留旧事实与外来身份拒绝，以及原回答／状态读取行为。
- 首次后端新 7 项有 1 项失败：测试构造 COMPLETED 时缺 ended_at；修复后再次有 1 项失败：FAILED 缺 error_code／error_message。补齐隔离库夹具的结束时间、失败信息及取消原因后通过；不是生产逻辑失败。
- 首次前端专项因 Node strip-only 不支持 constructor 参数属性而未执行。将 ModelCallReader 改为普通字段赋值后 5 项通过，后续 49 项组合通过。
- 首次 `npm run build`：TypeScript 与 Vite 生产构建通过，1236 个模块。已有大于 500KB chunk 提示保留。最终构建／差异与清理结果补在下方。
- SQLite 测试均使用 TemporaryDirectory，按用例清理；不保留测试 JSON、截图、录像或原始日志。

## 2. 实际保存数据只读核对

新 GET 接口返回运行 17 的调用 20，并通过前端实际 decoder：输入 126002、输出 2075、合计 128077、缓存命中 66432、耗时 12391ms；缓存未重复计入合计。

预检输入 127023，冻结输入预算 131072／输出 8192／总 139264，六项预检计数 3917、122082、42、2、20558、1698。界面明确独立统计与完整 User JSON 重叠。

上下文顺序为 System、模板、CURRENT 读取正文、历史、本轮输入、来源、身份／权限；读取正文 322 区块、50 个已有章节标题；历史身份为 20、22、24、26、27、29、31、33、34、35。没有补入窗口外的原始想法，也没有猜测其排除原因。

## 3. Chromium 页面只读观察

使用已安装 Playwright CLI，新建独立 headless 会话访问 `http://127.0.0.1:5173/requirements/3`。浏览器侧拒绝 GET／HEAD／OPTIONS 之外的请求；只填本地未提交消息以检查保留，不发送。CLI 临时文件放系统 Temp 独立目录，结束后清理。

- 对话初始显示 10 张请求记录；调用 20 摘要与接口一致，程序直接处理的确认没有虚构用量。
- 详情读取实际历史身份和正文版本；展开正文显示 322 个区块标题，各区块正文保持折叠，抽屉滚动区宽 394px／scrollWidth 394px，无横向溢出。
- 搜索“这个模板只是让你”只匹配保存的本轮输入；格式化原始请求解析后与接口 raw_request_json 完全一致。
- 打开／关闭详情前后输入和滚动 DOM 都是同一实例；本地未提交草稿保持，对话 scrollTop 前后均 12158，焦点返回“查看上下文”。
- 文档记录的运行 17 详情复用同一抽屉，实际合计 128077／缓存 66432 一致；抽屉高 466px，底部 687px，位于 720px 窗口内。
- 运行 15 显示“程序已处理，未调用模型”，没有模型上下文按钮。
- 历史失败运行 11 的三个尝试均显示，实际合计 380548；从调用 15 切换到调用 13 后，紧凑 JSON 与该次保存请求一致。用仅在隔离浏览器内存中的 Clipboard fixture 检查复制内容完全一致，未覆盖系统剪贴板。
- 独立刷新后激活 AI 页签：恰好 10 个摘要 GET、详细快照 GET 0、非只读请求 0、页面异常 0。完整上下文确实延后加载。

首次前端页面在旧后端重启之前出现新增接口 404；后端加载后读取恢复。该次会话旧控制台条目不用于判断新接口状态。

最后延后加载观察首次超时：刷新恢复了用户界面保存的“文档记录”页签，脚本误等隐藏 AI 面板的按钮。根据实际快照选择“AI 对话”后上述观察通过；应用隐藏面板没有发送摘要请求，符合暂停读取规则。

## 4. 服务与最终结果

首次加载前确认 RUNNING 运行 0、在途 LLM 0，消息 38、调用 20；核对现有进程与项目启动命令后重启后端，隐藏启动 launcher PID50120，前端原 5173 服务继续运行。

- 边界兼容性和章节数量展示补齐后，新后端 7 项专项再次通过；最终 `npm run build` 再次通过（含 TypeScript，1236 个模块），保留既有 chunk 提示。
- 最终后端加载前再次确认无运行中任务／在途调用，核对进程后加载完整收尾源码；当前 launcher PID11656，监听 PID1924／8000，前端 PID44400／5173 保持。
- GET 需求 3、生产页面、运行 17 调用列表及调用 20 详情均 200，前端 decoder 通过。8000 页面采用最终产物 `index-BIYsErnc.js`／`index-BdBUwHNZ.css`。
- 前后消息数均 38、调用数均 20、RUNNING／在途调用均 0。全部文档 id／content_version／markdown／block_state 的联合 SHA256 前后均 `5fb27005771189ba14a98155eb019eaba837b8e71ec3a8d1ea98d0aee4a946f9`；没有改用户正文或产生新模型调用。
- `git diff --check` 通过，现有 CRLF → LF 提示不影响退出状态。`tools/cleanup-test-artifacts.py`：JSON=0、screenshots=0。Playwright 独立会话已关闭，delete-data 确认没有用户数据。首次递归删除临时目录被自动审查拒绝；改为核对根路径、每个文件父目录／扩展名／非重解析点后，仅逐个删除本轮生成的 YML／日志，再移除空目录，最终 Test-Path=False。未留本轮快照、控制台原始日志、截图、JSON 报告或录像。

## 5. 未覆盖

未恢复全项目验收，没有真实 Provider 新调用、真实计数或并发业务提交。网络异常／取消／失败主要由隔离库和读取 owner 专项覆盖，不代用户在当前业务数据中制造这些状态。复制入口复用浏览器 Clipboard API，权限失败会显示提示；未覆盖所有浏览器／操作系统剪贴板权限组合。大正文按本次保存的 322 区块样本观察，没有对任意体积宣称性能保证。
