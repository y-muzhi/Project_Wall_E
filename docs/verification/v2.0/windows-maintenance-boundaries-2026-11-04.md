# V2.0升级路径身份与私有包权限

日期：2026-11-04，HEAD 28a7c9e，V2源码未提交。仅新建隔离临时文件／目录；未打开正常业务库、修改已有用户目录权限、启停服务或真实模型／计数调用。

设计依据BE7.1.4。实现前核对Microsoft官方[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)、[文件ID结构](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_id_info)、[GetFileInformationByHandleEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex)、[卷信息](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getvolumeinformationbyhandlew)、[安全描述符转换](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertstringsecuritydescriptortosecuritydescriptorw)、[GetNamedSecurityInfoW](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getnamedsecurityinfow)及GetAce／GetTokenInformation定义。只依据官方SDK规则和本机真实API检查，不按路径字符串或PID猜身份。

- windows_local_paths.py：仅本地绝对普通路径；在IO前拒绝网络／扩展设备命名空间、相对／点段、NTFS流、保留设备名、歧义尾空格和分隔符。逐级OPEN_EXISTING＋OPEN_REPARSE_POINT，核对真实NTFS及持久ACL能力、最终路径、64位卷身份与128位文件ID；拒绝reparse及多硬链接文件。持有文件和全部祖先句柄，不共享DELETE，阻止重命名／替换，同时允许SQLite正常读写。verify重读同句柄身份，不以mtime当身份。
- windows_private_package.py：原生读取当前非AppContainer／非模拟线程操作者SID，不开启特权或改变token；仅新建目录时设置当前用户唯一FullAccess且受保护的DACL，文件／子目录按同SID继承。已有目录拒绝，不修补原源库／用户目录ACL。打开／重验包时核对owner、实际ACE、保护位及继承；成员路径不能越界，检查其真实路径与DACL。权限异常保留原资产，无自动删除策略。
- 本地卷兼容检查支持固定／可移动本地卷，仍须实际NTFS／ACL／文件ID支持；本轮实际介质仅当前本地NTFS，没有其他介质兼容证明。

检查命令：tools/python-v20.py tools/quality_python.py backend/tests/infrastructure/test_v20_windows_private_package.py backend/tests/infrastructure/test_v20_windows_local_paths.py -q -p no:cacheprovider --tb=short，使用tools.quality_gate.environment的自有临时目录与外网／正常数据保护。

最终12通过、22子场景通过（0.60秒）：真实文件追加不改变身份；替换文件／祖先目录在持有期间失败、关闭后允许；硬链接和目录junction实际创建并被拒绝；失败释放句柄；原生私有目录及子项继承；已有目录不覆盖；运行中故意放宽临时包DACL被重验发现；取消保护／放宽子文件／路径越界拒绝；关闭后可移动。只更改本轮自有临时包权限，测试后清理。

首次受限环境不允许创建hardlink／junction，4项通过、2项因权限失败；改在获准的隔离环境实际验证，不将权限失败当实现通过。PowerShell测试错误输出最初误用UTF-8解码本地字节，夹具已改为字节捕获；无该警告的最终检查通过。后端148文件格式、diff检查通过；专属native临时目录核对无残留。未保留原始JSON、输出日志或截图。

这只是显式维护的路径与权限前提：尚无实际Schema发布pin、plan／rehearse／apply／recover／check、审计备份或磁盘检查接入；不能用于正常库升级。本轮没有LPAC受限执行进程／浏览器文件访问／OpenCode／Guard停止或供应方证据，不把包DACL检查写成整套Windows隔离准入。
