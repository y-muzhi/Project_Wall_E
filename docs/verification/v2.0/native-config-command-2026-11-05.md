# V2.0原生固定私有配置解析命令验证

日期：2026-11-05。依据BE0.17-draft-17／DRAFT 7.7.2及7.7.6、原7.3普通控制方／Job／STDIO／nonce规则。代码为28a7c9e后的未提交V2工作区，未更新服务、正常仓库／数据或任何系统安装／网络策略。

## 输入、输出及不变量

git_config_command.ConfigParseCommand只接受原PrivateConfigCopy和LockedConfigSource；后者必须是同一已核对私有包内的实际空全局配置。持有原source／copy数据身份及SHA、包DACL／目录身份，非秘密facts进入原control_git_input_sha256。原目录必须同一私有包，.git存在即拒绝；不接收任意路径、命令名、额外参数或环境覆盖。

固定argv为config --file <原私有副本> --no-includes --null --list。从空字典重建Windows／受控PATH、私有HOME／XDG／TEMP、实际空global、NOSYSTEM、无交互／lazy-fetch／replace及可选锁；ceiling固定私有cwd的父目录以阻止上层仓库发现。此规则只用于配置解析，不替代进入真实仓库前的完整布局／白名单准入。[Git配置文档](https://git-scm.com/docs/git-config)、[Git环境变量文档](https://git-scm.com/docs/git)。

windows_native_process在原固定--version之外仅增加严格类型ConfigParseCommand，直接提取同内容tuple仍拒绝。原普通控制方token、完整Git包核对、挂起创建／原子Job与STDIO及持久CREATE／RESUME链路保持。typed命令在实际创建前取得原copy／empty借用，原根关闭前要求实际退出及完整空Job；未知创建／恢复／成员观察继续保留原owner和借用，不能提前删副本或改用新资源。原版本探测输入摘要保持原结构。

runtime_control_git.register将同一typed命令对象纳入原scope绑定，不能用另一个字节相同的命令owner替换；原Entry持有它，原创建／停止／观察／私有追加回执路径复用，不另建调度账本。Git stdout仍留原后端STDIO，不经Guard正文通道或写入NativeReceipt；真实解析后的白名单事实由原git_local_config验证。

## 实际检查及修复

环境：Python3.13.5／固定SQLite3.54.1／MinGit2.56.0.windows.4／Ruff0.17.3，普通非提升非AppContainer测试环境。tools/python-v20.py及quality_python.py、quality_gate.environment限制专属.tmp根、隔离数据、禁外网；新建私有包DACL仅施加本轮临时目录。没有真实模型或计数API。

1. 初版新专项9通过／3夹具错误：误用Guard自身进程作控制方，原GUARD_SELF_TOKEN_REJECTED正确拒绝。改用既有独立STDIO控制方peer，未放宽产品身份规则。
2. 独立peer后12通过／1清理错误：测试已显式释放原进程句柄，teardown又等待None。改按原Entry.released区别已释放状态，不重开PID／不改产品退出证据。
3. 配置命令／原生创建／原资源登记／原STDIO四文件63通过，67.59秒。命令：test_v20_git_config_command.py、test_v20_windows_native_process.py、test_v20_runtime_control_git.py、test_v20_windows_stdio.py，使用-q -p no:cacheprovider --tb=short及专属--basetemp。
4. 增加sha256、创建后身份验证失败及恢复ACK未知后，配置命令／副本／源／白名单四文件首轮110通过／1失败，23.72秒：sha256夹具预期仍为sha1的formatversion=0，产品实际返回正确1及extensions.objectformat=sha256。只修精确预期，最终同四文件111通过，24.63秒：test_v20_git_config_command.py／test_v20_windows_config_copy.py／test_v20_windows_config_source.py／test_git_local_config.py。
5. 实际通过AsUser创建固定Git并分阶段持久恢复，直接读取原peer STDOUT的完整NUL输出，sha1及sha256配置分别通过原白名单；stderr实际空。原配置／副本正文保持到Git退出且Job完整为空后，原Registry释放后借用才归零。NativeReceipt实际不含测试配置值。
6. 创建后验证失败仍留原挂起根／副本借用且不重建；未知Resume ACK不重复ResumeThread；退出后Job观察不完整仍拒绝关闭／释放配置。环境注入测试只比较新建受控字典，未读取真实凭据或发外部请求。

后端184文件格式、三个受影响模块lint、git diff --check及db20-r7实际load_release通过；manifest仍88dcb99509f6184f5289bffc403f6043130a43f9ada9fdb3f962c16604781860。最终复核如有后续改变另记。既有httpx弃用提示未修改依赖。

所有自有控制方／Git及Job成员退出，测试JSON、原始输出／配置、临时私有包和journal随专属临时根清理。正常用户服务、data和.env.local未操作。

## 未覆盖

这是固定解析命令的原生／资源组合验证，不是完整Guard认证Pipe、SYSTEM部署或LPAC／WFP准入。仍需原仓库完整布局／锁／对象闭包、配置结果与当前原操作绑定、生产有界并发STDIO消费／超时及清理调用方、其余固定Git命令、GitReceipt、原交付窗口／业务派发栅栏及成功后核对。没有新增业务HTTP或前端页面；目录runtime_admitted继续false，不能据解析成功声明仓库可交付或整个V2完成。
