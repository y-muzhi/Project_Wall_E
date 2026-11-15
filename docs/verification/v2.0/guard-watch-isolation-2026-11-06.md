# Guard监视与执行锁分离（2026-11-06）

按[通信细化](../../iterations/pending/v2.0/WALL-E.Guard本机通信实施细化_V_2.0.md)继续原句柄所有权，正式设计未合并，V2未提交。

实际竞争用例在actor持有原source._gate时从另一线程调用sweep_controller，修前真实失败（2.18秒）：监视器等待执行令牌也使用的同一源对象锁。ControlGitRegistry构造时最后取得原句柄同权只读副本，watch及窄恢复的退出核对使用该独立对象；不按PID重开。close_watch先封闭新准入、原scope／Job／root检查及监视线程退出通过后，再关闭该只读副本，失败保持原owner。构造顺序避免复制后再新增可失败分配，未启动线程也可回收原观察句柄；第二个仅观察Registry测试补显式关闭，不遗留新句柄。

修正后三文件16通过39.51秒；随后增加窄恢复不等待actor源对象及watch句柄关闭失败保留，13文件225通过、1条既有Starlette弃用警告，122.88秒，含真实固定Git配置和metadata两格式、Guard崩溃／AsUser。该结果在随后部分准备改动之前，不替新改动验收。226个app文件格式及相关lint／diff通过。

普通非提升隔离临时目录／管道／自有Job，未操作正常库／服务／ACL或模型。程序准入的正向仍为明确端口，非SYSTEM／实际保护包。ready=false。
