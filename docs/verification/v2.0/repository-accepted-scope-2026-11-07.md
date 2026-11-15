# 仓库原登记派发前的接收证据验证

- 2026-11-07，V2 工作区，db20-r16。原登记 VALIDATE 开始及后续 Guard 原范围读取，与 API17 共用原不可变接收核验。须同读快照验证原路由、键、固定输入字节、成功 202、原操作和预留资源身份。缺失或不符进入存储错误，原记录不被覆盖。
- 固定 SQLite 3.54.1 及隔离 Windows，`test_repository_acceptance.py`、`test_repository_registration.py`、`test_repository_operations.py`、`test_v20_guard_control_git_transport.py` 相关表达式专项 5 项通过、45 项未选，23.58 秒。实际数据库原接收通过，变更原操作、资源、输入、键均拒绝。回归实际原 API17、登记成功／已知来源失败和原 CREATE 回复丢失后重连清理。
- 237 个 app 文件 Ruff 格式、受影响八模块 lint、git diff --check 通过。db20-r16 登记源码散列全部匹配，维护 SQL及正式设计仍沿原发布。生产宿主、实际批准执行环境及 C01／C02 HTTP 调度为后续工作。
