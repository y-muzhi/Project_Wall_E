# V2.0原生Git配置源读取组件验证

日期：2026-11-05；设计BE0.17-draft-17／7.7.2，V2工作区未提交。仅本轮新建隔离文件／Git库，无正常配置／业务库／用户仓库读取或服务更新，无模型／计数调用。

## 已实现

windows_config_source.py提供LockedConfigSource，输入为程序已选定本地配置路径、正安全max_file_bytes及可选原FileIdentity。复用LocalPathGuard的实际NTFS对象／祖先边界、windows_executable_pin的已绑定只读Native API及特殊属性策略，未另建解释器／进程入口或PE判断。

持有非继承GENERIC_READ数据句柄，只共享读，保持原祖先／文件身份到close；实际GetFileType／GetFileInformationByHandle／原FileID核对，拒绝重定向／hardlink及不支持属性。分块读取前检查大小上限，原句柄从0开始读到真实EOF；读前／后原身份与大小一致，不以读取失败造空配置；空文件必须真实成功。原字节交config_source_sha256核对有界／无NUL，ConfigSourceSnapshot仅在后端持有，repr无正文或原路径。snapshot属性只读，verify重新核对原句柄与字节，未开放时不复用。

关闭失败保留具体原数据句柄及祖先guard，retained_owner供原调用方继续关闭；进入closing后拒绝重新读取，不重开路径或丢弃引用。真实共享冲突映射SOURCE_BUSY，原文件／字节身份变化映射SOURCE_CHANGED，其他不支持路径明确拒绝。

## 实际检查

Windows11／NTFS，项目Python3.13.5，Ruff0.17.3；quality_python及脱敏环境，专属临时根。实际原生环境经正常自动审批运行，无提升系统权限／安装／改ACL。命令均以tools/python-v20.py tools/quality_python.py启动。

- 首次新读取＋原配置／程序pin三文件：113通过／1失败，1.50秒。夹具名nul.config恰为Windows保留设备名，现有路径策略在读取前正确拒绝；已改自有文件名，不放宽产品保护。
- 修后test_v20_windows_config_source.py＋test_git_local_config.py：80通过，0.91秒，包含23原生读取及57配置解析专项。
- 追加快照私有repr／只读属性，以及真实固定Git配置源与原生原句柄一致性后：读取23＋完整固定Git向量1，共24通过，4.72秒。真实sha1／sha256配置摘要与worker原副本／Git解析输出核对；worker仍独立，不导入产品代码。它先完成Git解析，父进程随后锁定原配置并重验原摘要；不冒充生产全过程持锁解析。
- 覆盖非继承、原字节／多块／摘要／可选FileID、实际写入者冲突、阻止替换与祖先改名、真实空／缺失、容量／类型／原NUL、hardlink、特殊属性与ReadFile／seek故障、关闭及构造清理失败保持。失败后能只释放本轮句柄再正常读取，未关闭他人writer。
- 现有程序pin34项在首轮全部通过，本批未改其源码；随后仅重跑受影响新路径。最终179个backend/app格式、新三模块lint及git diff --check通过，当前db20-r7 source pin一致。既有httpx弃用告警保留。

所有原生测试文件／临时JSON／Git库及子进程随本轮专属根／Job清理；只留本Markdown。没有截图／原始日志／JSON报告留存。

## 未覆盖及接续

当前是配置文件默认数据流读取，不是完整CONTENT20捕获器；未验证全部命名数据流、QUIESCE或真实掉电。写映射与不受合作窗口约束的恶意外部主体不因共享锁获得额外防御承诺。

尚须把源lease、原DACL私有配置副本、固定Git成功parse、布局／config.worktree／lock检查、受控环境和最终指纹核对接成实际仓库操作；不能据此宣称Q20-GIT或Guard／LPAC/WFP准入。现有Native控制器仍只登记--version，不直接传任意参数。完整配置版本／设置和全部任务链路继续实施。
