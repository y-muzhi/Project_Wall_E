# 当前控制方绑定与Guard公共请求头（2026-11-06）

未提交V2工作区，正式设计／db20-r14／code20-r2未改。本单元按[本机通信细化](../../iterations/pending/v2.0/WALL-E.Guard本机通信实施细化_V_2.0.md)复用原ProcessLock、NativeProcessIdentity、NamedPipePeerLease及LaunchScope，不执行Guard动作或读业务SQLite。

## 实现

guard_controller_binding.py：后端只读自己的真实OS身份并核对原实际ProcessLock／owner_epoch；Guard从原CLIENT peer独立读取实际控制方身份，双方以同安装引用、同原epoch和Native身份确定controller_ref。它是路由摘要，不是凭证／签名，不采纳序列化PID或锁声明；新epoch产生不同引用，旧绑定不作为当前发送资格。Guard接收同一连接的一份固定绑定，每次公共头解析重新核对该原peer，不按每个packet重建绑定。

guard_request_header.py：严格十字段／WIN20-ISOLATION-1及原七动作、原controller／epoch、operation／step／nonce；复用LaunchScope安全整数及nonce校验，原binding_ref有无按动作核对；OBSERVE显式定位原动作，拒绝递归OBSERVE或隐含latest。input固定为确定JSON快照、读出为独立副本，名称明确unvalidated_input_json；尚未获得各动作语义／资源和准入验证，不交Native callback，不返回业务成功。

## 实际检查

环境与隔离沿[传输检查](guard-pipe-transport-2026-11-06.md)：普通非提升进程、临时锁／本机管道、自有Job，无正常数据库／凭据／外网／模型或服务更新；源码同目录临时文件fsync及os.replace。

- test_v20_guard_controller_binding.py＋test_v20_guard_pipe_frames.py＋test_v20_windows_guard_pipe_io.py，73通过、1条既有Starlette弃用警告，4.02秒。新单元29项，组合不求和。
- 真实后台测试进程持有本轮实际ProcessLock，经真实管道只发送原epoch／引用；Guard以实际原peer独立计算完全相同引用，没有互读对方锁文件。其他向量覆盖原锁释放／同PID新epoch、非UUID／非v4／非小写、序列化声明、服务端角色冒充后端、另一实际peer、缺字段／越界scope／任意路径资源引用、未知opcode与冻结输入。
- 最终全部相关10文件177通过、1同类警告，7.45秒。包括前批全部9通信／进程／令牌／固定程序文件＋新增绑定文件。220个app文件Ruff format、两模块lint及git diff --check通过。没有活动检查或待取回执；临时产物随原owner清理。

## 未完成与待确认

此处只处理当前控制方。后端重启后新peer／epoch如何定向旧scope，原设计未明确权限边界；[窄恢复提案](../../iterations/pending/v2.0/WALL-E.Guard重启跨控制方恢复权限细化_V_2.0.md)已保存并通过异步问题提交用户确认，尚未取得答复，不实施新权限。不因此停止其他独立实现。

原七动作的严格实际输入、同scope准备资源、完整Guard／Registry生产派发、保护运行包、安装及LPAC-WFP仍未完成。临时Python测试程序不是保护包证明，Guard不能远程证明后端业务锁实际持有；本地发送检查和实际接收程序信任分别负责。无新HTTP、UI或真实供应方证据，V2仍19条实际HTTP、ready=false。
