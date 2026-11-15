# V2.0默认Schema200启动与文档准入保留

日期：2026-11-05；HEAD 28a7c9e，V2未提交。仅隔离库、进程内HTTP及替换监听层的自有测试子进程；未运行正常服务、读实际凭据或调用供应方。

实现：service.create_app默认加载编译pin的Schema200；私人测试注入可继续验证冻结151文档边界。backend.app.__main__将固定SQLite激活移到uvicorn／service／database导入前，正常入口不初始化／迁移。tools/ai-service.py离线readiness只核对资源／固定运行包，数据库／凭据／供应方／服务均为0；明确start先独立200检查，再原文档资源准入，最后读取被明确选择的本地凭据。根README改为V2实施导航及当前数据库规则，旧V1.5资料保留历史链接。

实际发布：当前db20-r3，manifest SHA256 710c41eb5d55bda4077af2094fb545abc55e58974820b1f9c45778d4a918cb74。r1／r2均原字节保留；源码绑定新增主入口／service／ai-service，r2新增后单独版本；启动工具补独立schema检查后另发r3，没有覆盖旧SQL／清单。设计／schema字段或业务规则未改，不自动合并正式设计。

检查：四文件startup／原startup_tool／published_schema／schema_release，11通过（62.90秒）。原151默认工厂拒绝且完整typed源不变；缺失库不创建；实际200可启动并读列表。全新Python子进程直接走真正backend.app主入口，只有网络监听层替换，实际FastAPI／worker／SQL生命周期证明SQLite3.54.1先激活；不是TCP浏览器验收。旧文档准入使用真实已保存的离线调用夹具及原绝对证据源，把非空151与审计原字节复制到隔离副本，经真实plan／rehearse／apply后200启动，原准入检查通过才把夹具凭据交给被替换的serve；不读.env.local／不发Chat。

失败与修复：首轮11通过／2夹具失败（子进程未加入项目导入路径；旧测试局部导入遮蔽SchemaMismatch），夹具修复后12通过／1失败。实际发现无准入文件时current()可先返回OFFLINE_READY，启动工具未独立验证库而先报准入错误；增加真实database.transaction检查，固定在准入及凭据之前，r3复核11全通过。未放宽151拒绝或用更宽异常断言消除失败。

命令：显式.venv/Scripts/python.exe -B -X utf8 tools/python-v20.py tools/quality_python.py backend/tests/infrastructure/test_v20_startup.py backend/tests/guide/test_v15_startup_tool.py backend/tests/infrastructure/test_v20_published_schema.py backend/tests/infrastructure/test_v20_schema_release.py -q -p no:cacheprovider --tb=short --basetemp <专属临时目录>，配tools.quality_gate.environment。158文件Ruff格式与git diff --check通过；临时资产已自动清理，没有原始日志或JSON报告留存。

剩余：P1业务仓储／资格、客户端错误／回执与IDB、P2 Git／内容、Coding／Testing运行／模型／前端仍待完成。文档默认worker接线不表示代码执行器已接通。正常数据升级、服务启停、真实供应方、Windows隔离与浏览器／整版验收均无本轮证据，不越权执行。
