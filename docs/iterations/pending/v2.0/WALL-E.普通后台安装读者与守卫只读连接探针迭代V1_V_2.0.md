# 普通后台安装读者与守卫只读连接探针迭代V1（V2.0）

2026-11-14香港18:52，承接三小时任务、启动组实际预核及Program Files父目录事实。本项先登记后实施，现行BE7.3及Guard原程序认证／SCM／管道规则保持；两份DRAFT设计不自动合并。

原专用后台EXE只有正常HTTP与--verify-runtime，不能在不打开业务库的情况下稳定保留实际普通读者供管理员预核，也不能独立证明正常后台到已安装Guard的原SCM／进程／管道链。复用原ProgramPackageLease、connect_registered_guard与原Native权限核验，不新增业务API、请求协议或普通用户Guard降级。

新增两个互斥、显式CLI模式：
- --hold-installation-reader，必须给定本程序完整program-sha256，且仅冻结专用walle-backend.exe；全包／实际运行入口／普通非提升非AppContainer主身份核对后，维持全成员原字节锁并输出原PID／创建时刻。只接受原stdin匿名管道的EOF或固定STOP换行以退出，固定有界寿命，不读业务库／设计／模型／环境秘密，不监听服务或分配Job／任务。无管道、错误命令、摘要／入口／身份、超时或未知关闭均拒绝；父端不通过任意命令驱动此模式。
- --verify-guard，明确本program-sha256、guard-package及guard-sha256、installation-ref；固定两个完整程序及实际入口，严格走原SCM OWN_PROCESS、原SYSTEM进程、实际Guard镜像和原本机管道身份核验。无业务帧发送，不创建控制方业务操作／任务／Guard新nonce；成功只证明原进程／管道链，不等于后台完整程序在Guard的请求准入、CONTROL_GIT、SYSTEM来源赋值或业务验收。

模式不能混入--port、运行资源探针或另一模式的参数；正常--port和原--verify-runtime行为保持。源码／Python解释器不能冒充冻结后台；不关闭原权限检查，不以SCM显示RUNNING或PID存在代替原进程身份。新helper纳入固定后台构建源码清单，真实EXE检查及离线边界分开记录；自有读者／临时新包检查完成须退出并释放原文件锁。

本轮当前只实现／检查源码、离线及自有普通读者，不安装SYSTEM／SCM、不改WFP或用户服务。正式安装／启停后才可取得真正SYSTEM对端证据，未执行不得填通过。

 
## 本轮实现与证据

上述两个模式已接入原冻结后台入口。实际新1900程序包、原普通身份／包锁、STOP及真实300秒寿命检查已通过；未安装Guard连接按预期拒绝。详[验证记录](../../../verification/v2.0/backend-deployment-probes-2026-11-14.md)。正向SYSTEM连接尚未执行，不能以离线或负向结果替代。保留独立迭代，不自动合入正式设计。
