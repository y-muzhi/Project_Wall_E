# V2.0 仓库登记专用线程及后端寿命验证

2026-11-07，master 未提交 V2 工作区。Windows、项目锁定 Python、SQLite 3.54.1、固定 MinGit 2.56.0.windows.4、临时 SQLite 与真实 NTFS／Windows Job。实际启动及关闭使用 create_app lifespan；测试端口提供 Guard 普通账户连接和保护程序准入，不代表已安装 SYSTEM 或正式保护包。

- 专用线程首轮固定 MinGit、实际本机管道及无唤醒的原持久队列单项通过（18.82 秒）。调整实际启动接入后，test_v20_guard_control_git_transport.py、test_repository_registration_actor.py、test_repository_acceptance.py、test_v20_startup.py 初次组合 33 项通过（101.18 秒）。覆盖原 PENDING 取件、同键 202、实际登记、失回执后的原清理顺序、关闭线程及可重新获得同一数据库锁。
- 服务入口为可选受信 RegistrationInstallation。默认启动不从请求或环境生成安装配置。db20-r17 的 manifest SHA256 为 72ecfcccd369670fe5493d907c53d8c8b8f16a1f1fb3a8db8fe8fcdff1cf6097，因 service.py 固定来源更新，未改 SQL 和结构资源。
- 静态 lint 起初拒绝线程的宽泛异常捕获，改由专用单线程执行器传递原失败。该调整最终证据与 C01 接入一起复查。

最终 C01 接入后（db20-r18）同组合 34 项通过（111.50 秒）。在隔离 ASGI 通过正式 POST 收到 202，观测到提交后的唤醒调用但拦住投递，专用线程仍取到 SQLite 原接收。实际 Guard 管道执行固定 Git，GET 原操作为 SUCCEEDED，GET 同 ID 仓库，重放原 202。另以无安装配置的正常 ASGI 验证 503 不保存接收／ID，原已接收仍可重放，差异输入 409，非法参数 422。加同用户启动门后定向 4 项通过（31.70 秒），覆盖不同 Windows 用户时未打开私有根、已释放后端锁及实际 C01。r18 manifest SHA256 为 37320cae794c2e79da6e00547bac3a67975b7fa4416761bc3b84b24da5432f9b，三份结构文件与 r16 字节相同。

Ruff format 检查 242 个应用文件通过；新登记模块和实际 service lint 通过。对原 shared/command_execution.py 的扩展检查仍见基线已有的 Callable 来源、UTC 别名及通用 HTTP 错误转换三项诊断，无新增 lint 诊断。开发或正常服务、生产数据库和真实模型未进入验证范围。
