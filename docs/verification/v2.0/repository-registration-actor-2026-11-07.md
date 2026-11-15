# 仓库登记原队列执行所有者验证

- 2026-11-07，V2 工作区，db20-r16。RepositoryRegistrationActor 在绑定当前 ProcessLock 的所属线程，从 SQLite 选择最早的原 PENDING 登记。先核对原接收和空执行历史，再使用原认证管道和私有登记目录驱动既有 runner。已开始的操作只走核对，不进入待执行选择。
- 一次只持有一个原 runner。失败若本地原资源无法验证关闭，执行所有者保留原 runner 并拒绝继续取件或关闭。显式 cleanup 用新认证连接，只核对和释放同一原 scope，保留原业务 UNKNOWN。
- 固定 SQLite 3.54.1、隔离 Windows 进程和临时目录，test_repository_registration_actor.py、test_repository_acceptance.py、test_repository_registration.py、test_v20_guard_control_git_transport.py 共 39 项通过，47.68 秒。覆盖队列原 ID 顺序、取消前无副作用、跨线程拒绝、原 202 回放、实际 MinGit 登记成功、CREATE 回复丢失后暂停取件及原连接重接清理。
- 实际管道与 Guard 动作为真实测试资源，独立保护后端程序仍为测试准入端口。执行所有者尚未由正常服务的专用线程及 HTTP C01 唤醒。固定 Schema、正常业务库、用户服务和部署权限不涉及该批。
