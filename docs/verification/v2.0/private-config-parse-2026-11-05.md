# V2.0私有Git配置副本与真实解析验证

日期：2026-11-05。BE0.17-draft-17，7.7.2；V2仍为28a7c9e之后未提交工作区。仅隔离临时文件、私有测试目录及自有进程组；没有正常配置／仓库／业务库／用户服务或付费API操作。

## 实现与不变量

新增windows_config_copy.PrivateConfigCopy，复用原LockedConfigSource、PrivatePackageGuard及原生只读API；LockedConfigSource.hold新增原源借用计数。只接实际原对象，不接客户端正文／任意复制路径。源关闭或PK未激活立即拒绝；私有包权限不自动修复。

副本名由程序生成，CREATE_NEW不可覆盖；写原字节、支持短写、FlushFileBuffers后关闭writer。核对原文件ID及继承operator-only DACL，副本再由LockedConfigSource保持只读共享，原源／副本原身份、字节数、摘要、全部原字节均一致。parse_path借用前后再核对；借用期间副本不能关闭，副本存在期间原源不能关闭，嵌套及多个副本互不释放对方。

清理优先使用原CREATE_NEW句柄，或重新取得并核对原副本FileID的DELETE句柄；FILE_DISPOSITION_INFO按SDK BOOLEAN一字节布局标记原对象删除，原句柄关闭成功后才记清理。不会按同名路径盲删替换文件、不删原配置或整个私有包。源创建未知不按存在／缺失推断所有权；读／写／删除／关闭失败保留具体原句柄及父owner，closing后禁止复用，允许只继续原清理。

SetFileInformationByHandle的FileDispositionInfo及DELETE权限、关闭后删除依据Microsoft官方接口；具体NTFS行为另经真实专项核对。[接口文档](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle)、[BOOLEAN结构](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_disposition_info)。

## 实际检查

环境：Windows11 x64／NTFS，项目Python3.13.5／固定SQLite3.54.1，Ruff0.17.3。quality_python阻止网络，脱敏环境，独立.tmp根；原生正向检查经正常自动审批运行，未提升系统权限。测试DACL注入仅本轮新建目录，结束清理。

- 首次副本／原源／私有包三文件45通过／6子场景，1.85秒。覆盖真实DACL／独立FileID／原字节、原源持有、嵌套／多个副本、真实空文件、CREATE_NEW碰撞不删除旧文件、短写与write／flush失败、内部reader构造清理失败转交原父owner、read／mark-delete／delete-close失败保持、替换文件不删除、DACL变化不修复、取消及创建未知不重试。
- 初次真实Git五文件组合97通过／2失败，11.25秒；细化阶段诊断后确认失败在NONREPOSITORY。GIT_CEILING_DIRECTORIES设为cwd本身仍发现上层项目仓库；已改为cwd.parent，维持显式非仓库解析边界，没有放宽断言。
- 修后一次审批服务HTTP403未执行（非不安全判定）；未绕过审批。服务恢复后用同一审批入口重试，最终五文件99通过，12.33秒：test_git_private_config_parse.py、test_content_manifest_git_vectors.py、test_v20_windows_config_copy.py、test_v20_windows_config_source.py、test_git_local_config.py。
- 新真实独立worker在源／副本借用保持期间，用固定MinGit2.56.0.windows.4实际config --file <copy> --no-includes --null --list；sha1／sha256两份配置均成功。真实rev-parse先证实cwd未发现仓库；解析输出回原白名单，只得到非秘密facts。原进程退出与自有Job为空后才离开副本借用并删除；原源最后重验不变。
- 复用抽出的owned_git_environment测试helper，原二格式blob／tree／commit与配置向量继续通过。该helper是独立测试环境，不冒充生产环境准入。
- 180个backend/app格式、新模块lint、git diff --check及当前db20-r7 pin实际核对通过。既有httpx弃用提示保留。前端未改，未机械重跑492项。

本轮所有解析输出／JSON／源副本／临时Git库均由专属临时根清理，自有进程已退出，未留原始报告／日志／截图。本Markdown是本轮证据。

## 范围与接续

已验证“原源持有→私有原字节副本→真实Git解析→原源复核→精确副本清理”的组件组合。不是整个仓库登记或生产Guard调用：Native控制入口仍只登记--version，未新增任意参数／普通Shell回退。

仍待原仓库布局、config.worktree／lock、受控环境／空hooks及完整程序包、配置指纹／worktree、基线保留引用／Delivery事务及业务／HTTP调用方。没有使Q20-GIT或runtime_admitted变为true，也没有SYSTEM／LPAC-WFP或完整产品验收。进程退出／副本清理与业务Git写入结果将继续分别核对。
