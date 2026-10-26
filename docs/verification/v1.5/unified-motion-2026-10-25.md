# 统一展开收起动效专项检查

2026-10-25，M15-MOTION-01。用户授权系统全部同类展开／收起复用公共能力、实现并同步V1.5文档。原工作区已有多批未提交改动；本批只增量改前端及责任文档，不提交／推送，不修改后端业务、模型资源或用户数据。本页只记实际新证据，不承接旧真实调用许可。

## 离线与构建

Windows／项目现有Node、npm和锁文件。`frontend/src/shared/motion.ts`公共核心新增7项，覆盖立即状态、连续反向、过期RAF／完成回调、CSS名转换WAAPI、reduce／resize取消、缺动画支持／拖动降级及dispose／重新激活。初次motion＋layout13项通过，修复CSS属性转换后motion7项通过；最终`frontend`目录`npm.cmd test` **368 passed、0 failed／2695.175ms**；`npm.cmd run typecheck`退出0；`node.exe node_modules/vite/bin/vite.js build --outDir <本轮临时根>/frontend --emptyOutDir --logLevel warn`退出0，仅既有大chunk提醒。最终代码含编辑器、评论更多操作和草稿对照接入；原frontend/dist未覆盖。正式BE仅新增非AI生命周期后，`pytest backend/tests/infrastructure/test_collaboration_resources.py::test_resources_match_the_complete_design_source -q`另1 passed／3.07s，模型Prompt／指引／Schema与正式设计仍一致。

第一次真实观察暴露主导航主网格跳变：WAAPI不识别连字符CSS属性键，修复camel转换并新增契约专项。第二个缺口为文档导航按钮行增减导致正文top跳变，补保留按钮与height／padding过渡。第三个缺口为请求详情长正文关闭时立即卸载，补presence180及inert。编辑器接入第一次tsc发现hidden的until-found字符串类型，布尔化修复；最终类型通过。初次失败没有改写为通过。

## 实际隔离浏览器

Playwright技能／CLI，HeadlessChrome155.0.0.0／Windows10，100%缩放；独立`tools/serve-v15-offline.py --serve`真实HTTP／SQLite／Worker，仅私有Counter／Gateway，不带凭证、不访问真实供应方。临时端口63860，测试根walle-v15-browser-wpuxrhr4；named browser=walle-motion-20261025。以下逐帧数值为本机一次观测，不当作帧率SLA。

| 路径 | 实际结果 |
| --- | --- |
| 主导航／主网格 | 200→158.359→123.015→100.375→64，main.x逐帧等于nav.width，最大偏差0；快捷键连续反向收敛到64，旧动画结束未覆盖新状态 |
| 文档导航 | 网格200／6／872／6／420逐步到0／0／1078／6／420；controls使正文top76→87.719→98.891→106.625→111.42→114.42→120连续变化，闭合最终hidden |
| 辅助面板 | 一键宽420→553.296→667.328→740.812→783.969→858；关闭后两RAF立即重开仍显示且非inert，输入保留；连续指针拖动0个布局动画，几何宽575与aria-valuenow575一致 |
| DOM／输入／滚动 | 同一长文档87块、41行表格、80段，原DOM身份保持、scrollTop1250前后相等，未发送消息保留；无正文保存或额外Chat |
| 原生details | 操作设置内容高度0→36.734→113.797→173.656→268.734；长请求上下文修复后4207→2651→1474→828→482→282→0，闭合时子内容保留后卸载，inert立即生效 |
| 创建文档／确认／需求 | 稳定打开的创建模态关闭opacity1→.588→.301→.160→卸载；闭合立即inert／aria-hidden，焦点回＋；快速重开名称为空，不复活放弃内容。取消编辑确认框关闭立即inert，新建需求Esc退出后卸载 |
| 请求详情／筛选／单选／工具 | 请求详情仅GET保存快照，关闭inert并返“查看上下文”；筛选Esc后inert／aria-hidden，立即重开并等待240ms仍可用；状态单选与详情工具Esc关闭，不提交改动 |
| 大纲／评论／来源 | 新建隔离空白文档，经实际编辑形成Parent→Child，子章节36→22.719→12.578→7.031→4.109→0，inert立即生效；再展开成功。正常隔离评论更多操作36→22.734→12.5→7.063→4.109→0；来源浮层关闭立即inert／aria-hidden |
| 编辑器 | 更多格式高度34→20.516→10.969→6.047→3.469→0，闭合立即inert；链接表单Esc隐藏／inert、焦点回原编辑器。空白文档斜杠实际11项打开，Esc后opacity1→.587→.301→.159→.088→0，立即inert并保持编辑焦点；Ctrl+K上下文链接打开非inert，Esc关闭。编辑命令／选择所有权未改 |
| 响应式 | 1100px文档抽屉内第一次Esc只关闭创建模态且导航仍开，第二次才收起导航；主导航抽屉关闭后open=false／inert=true。1023进入BLOCKED并hidden正文，1024恢复SUPPORTED且无横向溢出；1600px恢复桌面 |
| 减少动态效果 | reduce时0个动画、创建模态立即卸载、CSS时长0；动画中切reduce取消布局动画，关闭区域最终hidden；恢复no-preference后可继续开合 |

初次长文档斜杠菜单两次键盘探针未成功定位到可插入空段，选区仍落在标题“/目标”，等待入口超时，原失败保留；随后通过正常UI新建空白文档，再实际打开11项斜杠菜单并验证退场，不借DOM强行打开、不修改标题保护。原长文档大纲均为同级，随后正常编辑空白文档建立两级标题，补齐真实层级折叠验证；评论更多操作亦通过正常UI隔离创建后实测。

未覆盖：原选区浮窗两次正常选中文字仍未出现，未把该入口记为浏览器通过；已接公共setMotionOpen及浮层CSS，其原选择／定位规则未改，需后续用可稳定触发的选区核对。恢复对照的完整冲突业务组合未专门造数重跑，已接共享内容折叠及即时inert，最终回归通过。不声称逐个实例、全部浏览器、真实中文IME／高倍缩放及所有断网组合已覆盖。

最终浏览器console Errors=0／Warnings=0。本轮仅为隔离长文档使用私有Counter／Gateway各1；真实模型／计数API均0，未操作用户库或关闭用户服务。清理完成：named browser已close，PTY89552／PID26420／63860收到stop后退出0，打印私有count_batches=1／chat=1及OWNED_TEMPORARY_SERVER_STOPPED_AND_OUTPUT_CLEANED；本轮TemporaryDirectory连同快照、唯一视觉截图、临时构建和业务库自动删除。后端8000／29692保持运行。


## 收尾运行及静态核对

初次读取5173模块／CSS拒绝连接；原57236进程不存在，原PTY45342已退出1，无足够错误正文可判因。按用户此前明确启动并使用前端的要求恢复已退出开发服务：frontend目录`npm.cmd run dev`，新PTY23234／PID60760，Vite8.3.2 ready。未停止或重启活跃后端8000／29692，未恢复历史取消的Windows Node崩溃专项。

最终5173/requirements、/src/shared/motion.ts和/src/shared/motion.css均GET200，模块含LayoutMotion／setMotionOpen，CSS含reduce及motion-disclosure；本轮临时根不存在。17份责任文档273本地链接全部有效，git diff --check退出0（既有CRLF提示），cleanup-test-artifacts.py --dry-run为JSON0／截图0。没有本轮剩余测试进程；仅保留用户后端及恢复后的开发前端，无额外真实API或Git写操作。
