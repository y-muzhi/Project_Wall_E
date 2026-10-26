# V1.5 运行入口与请求详情资源复用收口检查

2026-10-24（Asia/Hong_Kong）。在资源v15真实技术及26EV完成后，只改非AI的只读投影与本地启动助手。模型Prompt／Schema／Wire／计数／profile／执行链和冻结资源未改，未新增真实调用。用户库／服务、frontend/dist及Git未操作。

实现：guide/model_calls.py内部可选catalog及原GET API传runtime.catalog，避免重复装载；响应与保存快照完全一致。tools/ai-service.py默认离线只显示当前collaboration_context_v1资源预算，不读密钥／库或启服务；显式start先验证绝对已存在schema150库与正常同release准入，再安全读本机凭证，只配置该进程环境并调用原服务入口。旧库拒绝、不初始化／迁移／自动导入证据，启动异常不输出凭证。

命令`.venv/Scripts/python.exe -m pytest backend/tests/guide/test_v15_model_calls.py backend/tests/guide/test_v15_startup_tool.py -q -p no:cacheprovider`实际7 passed／50.64秒（70453，既有Starlette提示1条）。覆盖HTTP复用已有冻结资源、禁止重载／重编译／计数、投影逐字段等同；默认启动检查无库／密钥／服务；缺库／未准入不读密钥；真实隔离正常证据核验后仅模拟serve、环境只保留测试密钥且不输出。没有启动真实服务或调用供应方。

补旧schema150边界：启动3项最终专项再次3 passed／27.60秒（39071），额外验证schema4正常SQLite只读拒绝且原字节不变；旧阶段7项证据不机械累加成一个全量。正式模型设计源一致性1 passed／3.27秒，默认CLI `tools/ai-service.py`退出0，显示正确v15 release／131072输入／8192输出／139264总量，以及credentials_read=0／database_opened=0／provider_calls=0／service_started=0。

只读实际观测：同一个真实保存请求独立创建catalog路径3187.68ms，传已有catalog路径302.47ms，返回投影完全相等。之后显式禁止资源装载、compile_context、TokenizationGateway.count、ModelGateway.send和socket.connect，以SQLite mode=ro读取本批25个实际请求，全部READ_OK／8分区／8计数，总954.14ms。只记录一次本机时间，不作为SLA或浏览器端到端性能结论。

正式BE只在AI-RESOURCE投影／运维规则增加上述约束，当前SHA256=02acb5f3bf621ff2a10c362818529cc0f8bc5f5b4988cb3226336607fc1eead8；v15采用时BE9f7e6476861e8d954fc6be675973c6e829988b2c582a107367b3d764fb90bcdd不回写，模型文本源一致性通过。当前backend/app聚合SHA256=3d5458ba7f298041266c8230a4989ab553e0f98962b0fb410232239852892f42，实际供应方执行时9cf0a135…保持原记录。启动助手SHA256=4c364e54ad196ca39d8148b8b95b27326aca1a1afdb40d0be343df5fc4e9d894。

v9—v15资源长度／SHA逐项通过；112个本批正常证据聚合SHA仍d6c73a4bbc8c98049d34cec887757bd947eb2cfbd311d8071653a73a754ecc92，旧v14的112个仍ee4f872ee31e81f832ec16546dae3b7980f083a51dee8bd8f3bbde7b416f3d0b。git diff --check通过，仅既有CRLF规范化提示。用户服务8000／5173未启停；默认CLI与模拟启动不代表实际部署或用户库配置完成。

仍未覆盖／未执行：人工按BE8.3逐项语义审阅、用户业务库及同release准入配置、用户服务启动／生产静态部署。前端未改，不重跑既有355／tsc／临时构建。旧16个临时目录删除的自动审批拒绝项保留，不绕过；正常数据库、审计、来源、资源不清理。
