# V1.5 前后端启动及只读检查

2026-10-25（Asia/Hong_Kong）。用户明确要求启动前后端。启动前8000／5173无监听，现有data/wall-e.sqlite及其记录保留；未停止其他服务，未修改业务代码、冻结资源、frontend/dist或Git。

实际配置：为本次用户运行新建data/wall-e-v1.5.sqlite，显式绝对WALLE_DATABASE_PATH，原database init／check退出0、schema150、无迁移。原admit-v15-resource.py向新库导入正常技术来源data/v15-observation-20261024-v15-once/observation.sqlite的LLMUse1，核实state=LIVE_VERIFIED及release5ced9443c445aa10330e906a875fd4dafe69b6ebe0eb5e40179251b5eefb5d97；只写新库正常准入配置，无计数或Chat。

后端：项目根目录配置上述WALLE_DATABASE_PATH，执行`.venv/Scripts/python.exe tools/ai-service.py --start --credential-file <项目绝对路径>/.env.local`。助手校验准入后只读取本机凭证至进程环境，未输出密钥。Uvicorn单worker／无reload，127.0.0.1:8000，PID29692，本次PTY会话85080，Application startup complete。

前端：frontend目录`npm.cmd run dev`，Vite8.3.2，127.0.0.1:5173，监听PID57236，本次PTY会话45342，代理8000。使用当前源码，未覆盖旧静态dist。

只读检查：Python标准库urlopen分别GET后端/api/v1/requirements、前端/requirements、前端代理/api/v1/requirements，均200；两个API是正常JSON信封，前端HTML包含Vite客户端及root挂载点。SQLite mode=ro核对requirements=0、guide_runs=0、llm_uses=0，未创建演示正文、在途AI或供应方请求。此检查不是完整浏览器交互或语义验收。

服务按用户要求保持运行。接续先查端口／PID及原会话，不重复启动；进程ID可能退出后被系统复用，不仅凭本文数字停止进程。获准停止时核对归属后，优先向本次后端85080／前端45342会话发送Ctrl+C；不要误停其他进程。人工语义验收仍待审阅，本次启动不消耗或续用此前真实调用许可。


2026-10-25 M15-MOTION-01收尾运行更新：后端8000仍原29692／85080；旧前端57236／45342已退出1，5173无监听，日志不足以确定原因。按用户此前明确启动要求恢复已退出前端，frontend目录npm.cmd run dev，新PID60760／PTY23234、5173。页面、公共动效模块及CSS GET均200；不重启后端、不动用户库、不进行已取消崩溃专项。后续需停止前端时核实当前归属并使用23234，不再操作旧45342。详见[本轮记录](unified-motion-2026-10-25.md)。
