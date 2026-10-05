# 正式API生命周期验证范围（2026-10-05）

`backend/app/service.py::create_app`接入既有37 HTTP适配器、实际Database/ResourceCatalog、GuideWorker与同库幂等执行。启动只使用已初始化的库：原结构/版本核验、OS锁、旧claim清理和STARTUP恢复完成后才接入。`python -m backend.app`固定127.0.0.1:8000、一个worker、无reload、10秒ASGI drain配置；不自动建库或迁移，不提供测试关闭HTTP接口。关闭停止接入并退休所有公共HTTP实际事务，再关闭后台、释放锁；后台每运行已有独立SQL门禁。10秒不是SQLite阻塞/进程调度总墙钟SLA，原存储不确定结果与下一启动恢复仍适用。

4项实际ASGI/隔离SQLite专项验证启动前503、原真实创建接受/缺模型配置FAILED可查询及原键重放、遗留Run在首次HTTP前中断、第二实例拒绝、缺库不创建，以及实际HTTP写线程在关闭时回滚且无晚提交。慢写是显式诊断注入，仍由HTTP真正传入的LeasedDatabase开启实际SQL事务，不使用假业务响应。

3项真实子进程/TCP专项使用正式factory和实际uvicorn.Server：独立数据库CLI初始化、真实创建/读取、第二进程被同库OS锁拒绝且第一实例继续服务、正常ASGI退出与重启后的持久原键重放；显式阻塞后台进入编排前，真实HTTP接受的RUNNING运行在强制结束所有测试自有进程后由下一启动中断，LLMUse为0且GuideRun仍只有1条；正式`python -m backend.app`缺库确实startup失败、未进入监听。测试runner只以stdin IPC设置uvicorn.should_exit，生产无此入口。私有HeldWorker只用于制造进程崩溃前的真实接受状态，不是ORCH成功/模型效果证据。

初轮进程诊断日志保留。Windows可能把未监听端口报告为ConnectTimeout；另一轮发现虚拟环境python.exe可作为子解释器的启动器，单独结束启动器不能证明其子解释器立即死亡。最终强制结束只针对本测试创建且仍存活的PID进程树，并以实际OS锁获取（最多等待3秒）证明释放，不删锁文件、不将PID当执行权限。HTTP关闭测试的第一版夹具误用底层Database，已改为实际传入HTTP门禁数据库；生产保证未放宽。

最终[730完整后端回归](P2-2026-10-05T09-34-39-734Z.json)504.589秒通过，source/pip均0、254个backend与验证工具输入前后hash一致；其中正式main缺库路径由完整批次覆盖，7专项日志是之前factory/TCP批次。未运行真实Provider、付费请求、tokenizer效果验证或默认生产库。前端37业务绑定/完整页面、备份审计保留流程、干净安装和373原设计场景全量验收仍待完成。
