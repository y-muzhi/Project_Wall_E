# V2.0 原 TASK 的 LPAC 目录角色

2026-11-08（Asia/Hong_Kong），Windows x64／NTFS，工作树基线 `28a7c9e`，固定 SQLite 3.54.1。对照 BE 0.17-draft-17 §7.3.1—7.3.3／§7.4.4。 [独立迭代](../../iterations/pending/v2.0/WALL-E.Windows受管执行与完整停止迭代_V_2.0.md)

- 从真实普通控制方进程、原 Guard Journal 及首次 TASK PREPARE 获取原目录 nonce。实测新建 6 个角色目录，逐个核对原卷／FileID、保护 DACL、原包 SID、OWNER_RIGHTS、低或中完整性标签。子文件实际读回可写、只读、只读执行的不同掩码与标签。STOP 先关闭时不创建目录，取消后的已创建目录留在原 owner；重复和已存在路径拒绝接管。
- 初轮带保护 SACL 的 CreateDirectoryW 返回 1314。单独用原句柄设置标签的尝试返回 5。最终按创建时的保护 DACL 和普通标签 ACE 一次提交，并验证实际读回，不启用额外系统权限。扩大组合首轮 93 通过、1 失败，子文件 ACE 由本机 NTFS 写入实际权限而未保留继承标记；夹具修正为核对权限和标签，并接受 0／INHERITED_ACE 两种只用于记录的标志。 [Microsoft 文件权限](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights) [Microsoft 安全信息标志](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-information)
- 通过 `tools.quality_gate.environment`、临时 `--basetemp`、`WALLE_TEST_CONTROLLER_POSITIVE=1` 运行 `.venv/Scripts/python.exe -B tools/python-v20.py tools/quality_python.py -q -p no:cacheprovider --tb=short`。选取 infrastructure 的 `test_v20_windows_task_directories.py`、`test_v20_windows_job.py`、`test_v20_guard_task_network.py`、`test_v20_wfp_install_transaction.py`、`test_v20_guard_action_journal.py` 和 `test_v20_runtime_launch_journal.py`。最终 **94 项通过**（8.63 秒），仅既有 Starlette 弃用提示。组合临时目录均已清理。
- 应用 281 文件 Ruff 格式、3 个改动源码 Ruff lint 及 `git diff --check` 通过。仅既有前端文件 CRLF 提示。
- 挂起 LPAC 探针分别尝试固定 Windows 系统二进制和自有临时 RX 目录中的同一文件，CreateProcessW 均返回 2。未得到进程令牌；未注册系统／用户 profile，也未修改现有目录 ACL 或防火墙。已通过的部分是 NTFS 目录和子文件结构证据。实际 LPAC 访问、生产 PREPARE 分配、固定内容发布、完整启动及受保护 SYSTEM 部署仍待。 [Microsoft LPAC 进程属性](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)
