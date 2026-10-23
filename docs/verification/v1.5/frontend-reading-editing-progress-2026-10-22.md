# V1.5 读取与编辑前端改造阶段检查

- 2026-10-22，未提交工作树，正式设计1.0／EFFECTIVE。活动操作摘要目标细化已合入，位置及设计摘要见同版merges记录；旧v9资源不改。
- 后端受影响联合回归：`.venv\Scripts\python.exe -m pytest backend/tests/requirements/test_v15_foundation.py backend/tests/test_v15_service_foundation.py backend/tests/documents/test_v15_documents.py backend/tests/documents/test_v15_editing.py backend/tests/revisions/test_v15_history.py backend/tests/comments/test_v15_comments.py -q -p no:cacheprovider`，38 passed，94.98秒（摘要目标补充前）。补充后需求／编辑专项19 passed，35.89秒。TemporaryDirectory退出清理，无监听服务。
- 前端命令（cwd frontend）：`node --test tests/autosave.test.mjs tests/v15-reading.test.mjs tests/v15-foundation.test.mjs`，21 passed，249.06毫秒。包括零文档摘要读取、跨阅读／编辑目标、严格新SourceRef／CONTENT标记、原ticket重放与其他动作同文冲突。控制端口测试不代替真实编辑器或浏览器。
- 旧autosave3项使用“GET同文即确认、重发新body”语义，本次按1.5原幂等动作核实修订；最终10项全通过，未放宽身份或并发保护。
- 完整`tsc --noEmit`当前仍失败：旧tests/browser调用缺显式文档／草稿ID、旧Revision字段、必有CURRENT等。源码错误已逐项修复，但过滤诊断不是完整检查通过。上次frontend-foundation中的构建只代表当时状态，不能用于此后改动。
- 当前新增目录／创建／元数据UI、EMPTY／parkedManual及SPEC文档绑定锁尚需后续专项和页面检查；不宣称本阶段交互验收。新恢复键、历史恢复入口、AI调用链及布局仍待继续。
- 未运行浏览器、真实模型或Tokenization API，未更新服务或用户数据，未生成截图／录像／原始日志或JSON报告。

## 本自然单元最终检查（2026-10-22）

当前工作树未提交。新目录／恢复键／编辑器投影专项与原读模型／autosave／基础／布局／本地输入专项联合：`node --test tests/detail-layout.test.mjs tests/v15-local-state.test.mjs tests/v15-directory.test.mjs tests/v15-reading.test.mjs tests/autosave.test.mjs tests/v15-foundation.test.mjs`，36 passed，261.41毫秒。完整`node node_modules/typescript/bin/tsc --noEmit`通过，含业务源码与浏览器诊断入口。临时`vite build --outDir <TemporaryDirectory>`通过，1242模块，501毫秒；目录退出清理，不覆盖dist。大chunk警告保留。

布局以实际可用宽度计算，导航抽屉不占正文宽度；单视图隐藏不卸载owner。页内ReadingPositions按req/doc/current_version或revision隔离；composer sessionStorage只存严格归属的未提交文字，UNKNOWN不清理，实际接受后清理；新键不读旧缓存。测试曾因窄布局旧宽度断言、Node strip-only不支持参数属性失败，已按真实宽度语义／显式字段修正，最终上述36项全通过。

浏览器诊断夹具增加显式doc／draft，未运行浏览器；旧AI路径及部分诊断运行期预期仍待B4。没有模型／计数调用、服务更新、用户数据写入或Git写操作。前文“当前tsc失败”只是中间状态，由本节替代；不能将编译及离线专项当作整版交互验收。
