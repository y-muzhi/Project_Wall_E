# 前后端服务启动检查（2026-10-26）

用户明确要求启动前后端。已读根AGENTS、当前断点、需求映射及运行说明；工作区既有未提交改动保留，本轮无业务代码修改或Git写操作。

启动前8000／5173均无监听，旧记录PID29692／60760不在运行。使用现有正常库data/wall-e-v1.5.sqlite，未初始化、清库或重新导入准入；凭证仅由启动助手从.env.local读取至进程，不输出内容。

- 后端：项目根目录设置绝对WALLE_DATABASE_PATH后执行`.\.venv\Scripts\python.exe tools/ai-service.py --start --credential-file <项目绝对路径>/.env.local`；单worker，127.0.0.1:8000，PID15852，PTY80858。
- 前端：frontend目录执行`npm.cmd run dev`；Vite8.3.2，127.0.0.1:5173，PID12440，PTY24965。
- Python urllib只读GET：8000/api/v1/requirements返回200／JSON；5173/requirements返回200／HTML；5173/api/v1/requirements代理返回200／JSON。仅记录状态与类型，未复制用户正文。
- 两端端口监听核实通过，进程保持运行。未运行专项、类型检查或生产构建，未覆盖frontend/dist，未调用真实模型或计数API，未代提交业务操作。

访问http://127.0.0.1:5173/requirements。后续先核对实际进程归属，避免重复启动；本次检查仅说明服务及只读链路可用，不代表新增产品验收或真实模型效果通过。
