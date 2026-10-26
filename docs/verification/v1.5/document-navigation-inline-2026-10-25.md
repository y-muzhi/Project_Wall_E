# 文档导航收起入口修正检查

2026-10-25，M15-NAV-02。用户截图拒绝收起后的全宽独占行。本批只改detail-frame.tsx及shared/styles.css／motion.css：展开图标移入既有页头工作台旁，单视图切换同样置入页头，删除旧detail-view-controls和该行高度presence／CSS，保持原布局owner及水平动效。没有新业务或模型权限。

命令：frontend目录npm.cmd run typecheck退出0；node.exe --test tests/detail-layout.test.mjs tests/motion.test.mjs **14 passed／94.24ms**。tools/serve-v15-offline.py --serve在全新TemporaryDirectory内部执行node vite build --outDir <临时根>/frontend，正常完成后才启动隔离服务；实际服务成功启动及最终退出0证明本轮临时生产构建通过，未覆盖frontend/dist。未为可逆入口位置另造测试，不重复此前373全量。

Playwright技能／CLI、Chrome155，私有真实HTTP／SQLite、端口59421／PID30148／PTY10527。正常UI建立隔离需求和固定框架文档，不触发任何Counter／Gateway。桌面1600×1000逐帧采样columns.top始终76、header高度67，仍有水平中间插值；展开按钮位于detail-header内，32×32、闭合后焦点正确，旧工具行DOM0。快速反向能完成，新截图已临时查看，文档标题和辅助面板不再被独立行下推。

稳定布局复验1600×600：闭合前／展开／再次闭合top均76，页头均67，scrollTop20→20→20，输入“本次开合保留的输入”保持。1100抽屉：空创建模态第一次Esc关闭模态、导航仍开且焦点新建文档，第二次Esc收起导航并回页头“展开文档导航”；窗口稳定后开合top均103，无横向溢出。1024自然可用宽1008，仍合法双视图、无额外行；初次探针假定其自动单视图而等待超时，未记通过。随后仅在隔离页将详情容器宽设980（实际columns宽964），由真实ResizeObserver触发单视图，两个切换按钮在页头可用、top103、旧工具行0；检查后移除临时约束。reduce下Enter打开／Esc关闭，0动画、焦点回正确入口。

初次在创建完成附近填入的输入在后续观察为空，未把该次当保留通过；稳定后重新填写，按上述真实开合完整复验通过。一次刚调整视口便测量得到旧页头94→67和滚动限值变化，补等待视口稳定后证明同一视口top与scroll恒定；未以过早采样宣布缺陷或成功。文档DOM身份保持；不据不可滚动样本的scroll0声称滚动保持。

最终console Errors0／Warnings0。named browser walle-navrow-20261025已close，10527收到stop后原30148／59421退出0，私有count_batches0／chat0、自动清理完成。临时根walle-v15-browser-pjdm3syl连同库、快照、截图及构建被原工具清理；用户8000／29692和5173／60760未启停，真实API0，用户数据／后端／冻结资源及Git无写操作。其他浏览器／高倍缩放／全部多标签组合未另行覆盖，整版语义验收状态不变。

收尾静态核对：12份责任文档本地链接检查无缺失，diff --check退出0（既有CRLF提示）；可清理JSON／截图0，本轮临时根不存在。用户8000／29692、5173／60760仍监听，5173当前detail-frame模块GET200，包含页头控件且不含旧独占行。
