# Guard后端程序包保护校验（2026-11-06）

未提交V2工作区；BE／FE设计未合并、db20-r15与code20-r2不变。按[先写的实施细化](../../iterations/pending/v2.0/WALL-E.Guard后端程序包准入实施细化_V_2.0.md)实现，只读核对，不安装／改ACL或服务。

guard_backend_program.py：BACKEND20-PROTECTED-1确定清单，固定walle-backend.exe入口及完整成员／大小／摘要、UTF8顺序、别名／冲突及容量拒绝；受信根及manifest hash来自Guard安装配置，不来自RPC。原CLIENT peer／primary token、固定图像FileID／字节、所有包文件／目录／manifest和祖先的真实有效权限；保持原路径／文件租约，重核内容、descriptor和完整成员，权限变化不能刷新原快照。查询同期限、取消、原线程、借用及清理失败保留原owner。

GuardControllerRecords明确record_peer_facts为无准入元数据，register_admitted仅接受同一实际peer的ProtectedBackendProgram lease并保存准入摘要。无准入旧记录不可覆盖升级，序列化admitted声明、错策略／程序／manifest拒绝。原登记不凭记录自身证明旧方退出，不授予恢复。

## 实际检查

普通非提升quality_gate隔离临时目录／管道／自有Job，quality_python.py、--basetemp自动清理，不使用正常业务库／凭据／外网／模型。

- 程序包＋原登记两文件52通过，5.17秒。首次审批服务403未执行，正常审批重试恢复后实际执行，未绕过审批。
- 增加清理失败保留token／peer、descriptor不能刷新、metadata不能被声明升级等检查；最终15文件309通过、1条既有Starlette弃用警告，16.91秒。范围为前批13文件及test_v20_guard_backend_program.py、test_v20_windows_access_check.py。
- 实际Native正向为基础令牌／有效权限／原文件／通信；本单元实际负向为用户可写包或祖先拒绝，以及失败清理仍保留原token和peer，重试同owner释放成功。严格清单、完整枚举和重新核对的正向使用明确标注的端口测试，仅验证算法，**没有实际受保护后端程序包的正向准入**。
- 222个app文件Ruff format、四个受影响模块lint、git diff --check通过；cleanup-test-artifacts.py --dry-run为JSON=0／screenshots=0，无活动检查或待取回执。

## 未覆盖及下一步

尚无真实打包／受保护walle-backend.exe、SYSTEM Guard／跨用户程序包和完整RuntimeBundle证据，ready／runtime_admitted仍false。程序包lease不替LPAC／WFP、模型来源或整任务STOP。后续接旧控制方实际退出或可靠封闭的窄恢复权限判断与原Registry动作／完整释放，生产Guard入口仍未连接；没有新增业务HTTP、实际页面或真实供应方证据。
