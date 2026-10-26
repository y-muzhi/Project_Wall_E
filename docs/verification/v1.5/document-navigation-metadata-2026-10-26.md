# 文档导航开关定位到文档状态行

2026-10-26，M15-NAV-02最终位置修正。用户明确指出将操作移到全局工作台页头不合理，指定文档名称下方、类型／Vn／确认状态文字左侧。本轮不把上一实现当成用户批准的规则。

实现：DetailFrame.document改为接收原导航按钮的渲染槽，detail.tsx将按钮传入DocumentMetadataBar.navigation；名称下方独立metadata-row中，按钮与状态文字同一行。开合都使用同一位置，桌面侧栏不重复开关，窄窗抽屉保留内部关闭；无阅读文档时复用空工作区现有操作区，AI单视图关闭抽屉返“文档”视图按钮。不新增业务owner／接口。改动frame、detail、directory-view及shared/styles，既有browser/detail-frame-probe接入新渲染槽。

检查：第一次tsc准确指出旧浏览器Probe仍直接传JSX，不符合新槽签名；同步实际Probe调用方后最终npm.cmd run typecheck退出0。相关layout＋motion14 passed／89.62ms；最终node.exe node_modules/vite/bin/vite.js build --outDir <本轮临时根>/frontend --emptyOutDir --logLevel warn退出0，仅既有chunk提醒，原frontend/dist未覆盖。不为可逆位置变更另造样式镜像测试，未重跑无关373全量。

Playwright技能／CLI，Chrome155、真实隔离HTTP／SQLite，端口60962／PID38640／PTY18139，named browser=walle-navmeta-20261026。通过UI创建隔离需求与固定框架文档，无计数或Chat。1600×1000展开时按钮x446／y120／32×32，状态文字x484／y122、名称bottom110：按钮在名称下方、状态左侧且垂直中心同为136；全局页头导航开关0、旧独占行0。收起时仍在同一状态行，label／aria-expanded正确、焦点在该按钮；快速反向开合可完成，未发业务或模型请求。

稳定1600×600：开合前后columns.top=76、metadata-row.top=118、正文scrollTop=20保持，输入“最终保留输入”保持。1100抽屉：先Esc退出空创建模态，导航保持展开；再Esc关闭导航，返状态行开关。首次延迟视觉观察发现创建模态的旧rAF随后把焦点转到名称；为该实际关闭路径增加新焦点保护，修复后等待300ms仍为“展开文档导航”且位于metadata-summary。

1024自然布局无横向溢出，按钮right64／状态文字left70，开关仍紧贴状态左侧；隔离页仅将详情容器临时约束980px，由真实ResizeObserver触发单视图：切AI、关闭抽屉后焦点为“文档”，Enter返文档后状态行开关可用。约束已移除。reduce下键盘开／关0动画、焦点在状态行，旧全局开关和独占行均0。无文档时原起步操作区开关1个。少量临时截图视觉核对了实际位置。

最终console Errors0／Warnings0。named browser已close，18139收到stop后原38640／60962退出0，私有count_batches0／chat0，打印自动清理完成。临时根walle-v15-browser-lk11gzmq连同数据库、快照、截图与生产构建由原工具清理；用户8000／29692、5173／60760未启停，真实API0，无用户业务数据／后端／冻结资源或Git写操作。

范围：本轮验证明确位置与原开合关键边界，不冒充全浏览器、高倍缩放或所有业务恢复组合通过。2026-10-25的页头位置证据保留为被替代实现，不能指导当前入口；整版人工语义签核状态不变。

收尾：责任文档本地链接无缺失，diff --check退出0（既有CRLF提示）；可清理JSON／截图0，原临时根不存在。用户8000／29692、5173／60760仍监听，5173当前metadata模块GET200，确含文档状态行实现。
