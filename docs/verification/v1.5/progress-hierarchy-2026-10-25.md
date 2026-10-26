# 大纲与进展信息层级优化专项检查

2026-10-25，M15-PROGRESS-01。用户要求层级、样式和内容重点清楚。本批只改前端展示、可见观察生命周期、私有离线夹具及V1.5责任文档；原后端业务／模型资源／用户库／Git不动，不启停用户服务。

## 实现及离线检查

新增discussion-presentation.ts只读投影与discussion-progress.css；重排discussion-view，detail传实际active，main导入，替代shared/styles旧扁平规则；新增5个展示专项。独立当前重点／已保存下一步，编号主线与主题状态，未决问题前置，依据按来源／状态区分，成果与判断要求分行，历史依据保留，设置集中且保留原四类C06命令及UNKNOWN／CONFIRMED核实。显式切主题成功后返当前重点并复用Toast；不把AI评估、数量或建议冒充确认、完整性、写入权限。

命令（frontend）：`node.exe --test tests/v15-discussion.test.mjs tests/v15-discussion-presentation.test.mjs` **10 passed／305.05ms**；最终`npm.cmd test` **373 passed、0 failed／4501.9428ms**；最终`npm.cmd run typecheck`退出0；`node.exe node_modules/vite/bin/vite.js build --outDir <本轮临时根>/frontend --emptyOutDir --logLevel warn`退出0，仅既有chunk体积提醒。没有覆盖frontend/dist，没有为CSS逐行造测试。5个投影专项验证当前阶段／未知主线不丢主题、争议与已更新分开及来源不升级、真实next_step不变自动操作、处置范围、源数据不变；原5项owner专项继续覆盖未知请求、确认后刷新失败、取消只读、占用／版本与HTTP原动作。

记录的来源与性质同为AI建议时只展示一次“AI建议”，避免重复标签。

实际首次观察发现展开后收到模型进展仍停在旧内容，补按已确认discussion_version刷新；只有可见AI且展开时有效，无新轮询。顶层onToggle检查target，内层折叠不误触读取；隐藏／收起清理观察，显式重新读取检查当前可见与在途读。业务命令结果核实沿原owner，不借动画或关闭中止。

## 实际浏览器

Playwright技能／CLI，HeadlessChrome155／Windows10、100%缩放；独立tools/serve-v15-offline.py，真实HTTP／SQLite／Worker及C07，私有Counter／Gateway。端口61697／PID60328／PTY11531，浏览器walle-progress-20261025。私有[progress-layout]分支含6主线、4主题、3条依据（用户陈述／AI建议）、长标题、待明确项／成果及保存的下一步；第二轮用于实际增量刷新，另一新需求用于窄窗，不在产品添加固定演示数据。

| 检查路径 | 实际结果 |
| --- | --- |
| 空状态／初次加载 | 无主题说明及6条主线可见，默认无伪主题；创建探针第一次漏选需求类型被正确拒绝，补选后正常创建，未把等待入口超时当产品缺陷 |
| 默认层级 | 当前重点含长主题／需要复核，下一步含明确关键决定及真实理由；只有当前主题所属“核心闭环”及其主题自动展开，6主线／4主题均保留，其他主线可独立展开 |
| 内层折叠 | 连续开关主线及当前主题后API请求为0，原待明确两条、AI建议／当前有效、成果要求及关联主题均完整可读 |
| 活跃新进展 | 面板一直展开，正常第二轮私有C07返回后自动显示新主题“目标”、主题数4→5，stale提示为空，未点重新读取；修复前旧内容观察如上保留 |
| 切换主题／反馈 | 原SET_FOCUS成功后显示“电影推荐的核心目标”、焦点“当前重点”、scrollTop=0，Toast可见，未发送输入保持“未发送输入保留”；没有额外Chat |
| 用户处置／阶段 | 正常SET_DISPOSITION保存“跨设备同步暂缓，先明确推荐反馈。”，本阶段用户处置显示暂缓及全文；阶段确认先取消仍需求探索，再确认才方案设计／当前阶段0主题，未混入旧主题，输入保持 |
| 可见读取边界 | 另一需求入口收起时收到实际模型进度，完整expand GET=0；点击展开后=1。最终代码切评论、重新读取详情再返AI，隐藏时完整expand GET=0，当前主题仍打开，未发送文字保留 |
| 来源 | 展开当前记录来源，正常GET读回本隔离用户消息“[progress-layout] 窄面板与主题信息检查。”，不计数／Chat |
| 布局 | 1920×1000、1440×800、1280×600、1100×800、1024×800，整页及主线／主题／重点内容横向溢出均false；发送footer底部分别958／758／558／766／766，均可达。显式收窄辅助面板至360px，长主题全文换行、内容无横向溢出 |
| 键盘／减少动态效果 | 键盘Space关闭／Enter展开顶层；reduce关闭时动画0且open=false，恢复设置后可继续操作；层级沿既有公共内容动效，无新独立时长 |
| 视觉复核 | 少量临时截图查看了重点／主线入口和窄面板的主题／待明确／记录内容，边界、标签、正文和次要说明可辨；内部滚动条留槽，顶层入口保持可达 |

一次CLI脚本因PowerShell原生引号拆参未执行，修正参数后同一原现场继续；无重复创建／发送副作用。最终console Errors=0／Warnings=0。

本轮私有Counter／Gateway实际各3，真实计数／模型API0。主题选择、处置及阶段三次程序命令均在自动清理的临时库，不触碰用户正文或业务库。原用户8000／29692、5173／60760保持运行，未重启；仅5173 HMR更新当前源码。

## 边界与清理

DISPUTED／SUPERSEDED及跨阶段处置分离由纯投影专项验证，未在浏览器另造完整旧依据替代链。UNKNOWN及确认后刷新失败为原owner离线证据，未冒充本轮真实断网／多标签组合；后两阶段完整内容、其他浏览器、高倍缩放、IME组合未逐项覆盖。无真实供应方调用或新模型效果验收，整版人工语义仍待审。

named browser已close；向11531发送stop后原60328／61697退出0，打印count_batches=3／chat=3和OWNED_TEMPORARY_SERVER_STOPPED_AND_OUTPUT_CLEANED；临时根walle-v15-browser-2w5pmrgr连同快照／截图／构建／库由原工具清理。最终独立TemporaryDirectory构建（walle-v15-progress-build-）也退出0并自动清理，未覆盖原dist。收尾16份责任文档257个本地链接全部有效，git diff --check退出0（既有CRLF提示），cleanup-test-artifacts.py --dry-run为JSON0／截图0。本轮隔离根不存在，8000／29692、5173／60760仍监听；5173展示模块和CSS GET均200，包含新重点层级、版本刷新、可见性控制和设置样式。正式BE及v15冻结manifest原SHA256保持。
