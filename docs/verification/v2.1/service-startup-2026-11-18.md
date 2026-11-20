# V2.1前后端服务启动

日期：2026-11-18（Asia/Hong_Kong）。用户明确要求启动前后端。本轮只启动独立工作区服务并检查实际页面，不提交推送、不迁移正常数据或触发真实模型/计数，不延续上一轮对服务启停的阶段限制。

## 实际启动

原8000/PID183580、5173/PID41048属于Documents/ChatGPT工作区，继续保留；未启停、未更新、未读取其业务库。当前工作区无已有数据库或.env文件，使用新的data/v2.1-local/walle.sqlite，经固定SQLite3.54.1和生产FormationDatabase.initialize建立Schema210/db21-r7空库。没有样例需求、历史数据复制或迁移。

前端通过现有锁定Vite8.3.2按当前源码构建至data/service-runtime-v21/frontend-dist，1.50秒通过；保留既有大chunk提示，不当作本轮性能验收。该构建供原生后端静态页面使用；开发前端另由Vite5174提供，WALLE_API_URL明确代理8001。

后端原生入口backend.app --schema-version 210 --port 8001启动完成，生产create_app/GuideWorker和真实Schema210数据库，不使用测试服务器、Mock、测试夹具或准入绕过。启动器PID70484/实际监听PID172612；前端Node PID311404。环境剥离继承的WALLE/模型凭据等配置，仅设置本工作区数据库/静态资源和前端API地址。原启动机制不读取凭据/调用供应方，AI执行仍由原准入/凭据链保护。

本地运行路径及启动方式见data/service-runtime-v21/service-state.md（该目录为本地常规服务资料，按既有gitignore不入库）。服务后台持续运行，本轮结束不清理用户要使用的新数据库或正常服务日志。

## 启动核对

- 后端8001/api/v1/requirements及前端5174/api/v1/requirements均HTTP200，success=true、空items及分页total=0；代理正确。
- 前端5174/与后端8001/均HTTP200；开发入口main.tsx内容完整，composer-view实际模块71935字符，包含GuideComposer导出和当前整篇文档确认入口。没有整文件写入/缓存修复或源码更改。
- 使用现有Playwright CLI0.1.24和独立临时Chrome只读打开5174，实际进入/requirements，标题“WALL-E · 需求工作台”，显示完整筛选/新建入口/表头与“暂无需求”；runtimeErrors=0、businessWrites=0。未创建需求、提交表单、编辑正文或触发AI。
- 初次探针把HTTP外层响应误按内部code检查，并错误要求main入口具备export；按实际success envelope及入口职责修正后完成检查。这是检查脚本假设，不是产品启动失败。
- 临时浏览器/配置、CLI快照和日志已随TemporaryDirectory清理，未留测试JSON/截图/录像/原始日志。正常服务日志仅用于后台运行。
- 12:19最后正式只读进程/端口核对：原5173/8000保持；新5174/PID311404与8001/PID172612保持；临时Chrome PID324356及临时CLI会话已关闭。

## 未执行

没有真实Tokenization/Chat，没有新LIVE准入；正常AI功能暂不可用，待真实评测/预算和对应准入。没有旧数据复制/迁移、原服务替换、正式设计合并、提交推送，也未恢复既有Windows Node崩溃专项。本次实际首页加载与接口就绪不替代整版验收。
