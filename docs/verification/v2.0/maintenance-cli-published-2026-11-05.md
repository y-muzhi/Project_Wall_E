# V2.0维护CLI、Schema发布与实际发布包回归

日期：2026-11-05；HEAD 28a7c9e，V2未提交。全部隔离临时副本；未操作正常业务库、.env.local、真实模型／计数或用户服务。

实现：
- tools/db-v20.py／schema_v20_cli.py提供plan、rehearse、apply、recover、check及独立init-v20／check-v20。无默认库／任意SQL／HTTP升级入口；计划命令要求明确路径、包、维护窗口及配置引用声明，后续命令要求原upgrade_id／计划摘要。init仅全新／真空，151不自动重建；check只读。异常只输出有界去秘密机器码，提交／回执未知返回PENDING_RECONCILIATION。
- schema_v20_publish.py／tools/schema-v20-release.py构造实际SQL／对象／完整来源清单，在新目录逐文件fsync、读回核验后同卷不覆盖发布，真实编译pin最后原子写入。失败保留原pin与已发布资源，不把存在目录当准入。暂存清理仅已核实的发布暂存绝对目录，无正常维护资产GC。
- 发布构建校验实际BE设计字节与DESIGN_SHA256；运行时绑定同设计来源／摘要、源码、实际SQLite DLL／SQL／最终结构。运行部署无需读取设计正文。实际db20-r1已发布，manifest SHA256 89172755ec2b3d8270ba8a003aeda663f985349ebeb0cc80fabc3550265ccc43；随后正常启动接线新增来源绑定，另发db20-r2，SHA256 d11a35be94b6bda748bbd98738809d601a7a3835590fed1f947ce01e7f70c3df。r1原字节保留，当前pin为r2。两个发布都只表示存储资源，不表示V2全版完成。

实际检查：
1. CLI／publish／release／flow四文件17通过、5子场景（58.79秒）；157文件格式及diff通过。
2. 真实强制结束本轮维护子进程：原DDL后、marker前结束恢复为完整151／NOT_APPLIED；durable commit后结束恢复为完整200／ALREADY_COMMITTED。2通过（15.96秒），真实OS锁释放、SQLite恢复及原备份证据核对；不冒充真实断电。
3. db20-r1实际编译pin＋14文件扩展组合：64通过、22子场景（205.87秒）。覆盖actual published fresh及非空151命令链、真实进程中断、CLI、flow、plan、assets、records、references、publish、release、state、audit owners、command HTTP及旧文档生产工厂。实际旧HTTP创建需求／空白文档及新关闭回执均成功，AI dispatch／LLMUse为0。
4. 正常启动入口及db20-r2接线验证正在下一单元执行，尚未把上项r1结果移作r2新增启动证据。

命令：显式.venv/Scripts/python.exe -B -X utf8 tools/python-v20.py tools/quality_python.py上述test_v20_*文件及backend/tests/test_v15_service_foundation.py，配tools.quality_gate.environment与自有临时--basetemp，-q -p no:cacheprovider --tb=short。本轮临时数据自动清理，无测试JSON／原始日志／截图留存；正式SQL／清单是实现资源，不是测试产物。

边界：正常数据升级、实际停启服务、真实供应方、LPAC／Guard／OpenCode／Git／前端尚无本轮验收；没有自动回滚、降级、恢复覆盖或GC。业务仓储／资格与客户端仍待后续单元，不能将上述存储发布称整版就绪。
