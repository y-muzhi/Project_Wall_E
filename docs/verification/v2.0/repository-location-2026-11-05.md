# 仓库原路径定位与配置源（2026-11-05）

## 依据与范围

master／HEAD28a7c9e，V2源码未提交。BE0.17-draft-17／FE0.16-draft-16（DRAFT），两份SHA256仍为1a8d277f25de570ce72e74a73ff763bf73f622fcf94b61f0820b78a1a5c6fd37／38557cee854697044ab7daba30f694738429be1235264a153851e8fc808cf3a7。本轮按7.7.1／.2／.5及APP-CODE-SETUP仓库准入前置推进，没有改正式设计或合并pending。

git_repository_location.py新增RepositoryLocationLease。输入是用户选定root、实际私有根列表、文件字节／句柄／元数据条目限制；输出是原root／gitdir／commondir／config的真实NTFS身份、config摘要、预期bare／linked类型及确定指纹。这是首次用Git进入仓库前的路径／源绑定组件，不能单独授予Git命令、证明完整对象历史或将仓库标为已准入。

复用LocalPathGuard、LockedConfigSource、现有metadata_pointer／metadata_head／_key／_overlap。主工作区.git目录、独立gitdir指针、linked的commondir及gitdir双向指针、bare候选分别核对；config及HEAD／指针的原文件持续持有，私有根与仓库路径不得重叠。不新建另一套文件读取器或worktree完整观察算法。

缺失、无权限、占用及变化均不作空配置。初始拒绝config.worktree、shallow、grafts、refs/replace、reftable、alternates／http-alternates和promisor包标识；包目录名称枚举有独立max_metadata_entries上限。缺失标记及包名称集合再核对发现变化返回SOURCE_CHANGED。此处未遍历证明全部对象／pack内容、全部refs和metadata子树；完整后续准入仍需要原Git事实及完整worktree／配置组合。

父路径及原文件身份由实际句柄复核；源配置可直接供旧PrivateConfigCopy／ConfigParseCommand使用。hold期间拒绝关闭；清理失败保留原子对象和祖先，重试只清理本owner。私有facts不带原配置正文，指纹明确包含角色、原FileID及源SHA，按确定顺序序列化，不依赖Python对象／set插入顺序。

## 检查

普通非提升环境，Python3.13.5／固定SQLite3.54.1／MinGit2.56.0.windows.4。经tools.quality_gate.environment专属临时根，tools/python-v20.py tools/quality_python.py，-q -p no:cacheprovider --tb=short及专属--basetemp。所有测试路径／仓库／私有副本为本轮新建夹具。

- 首轮新文件21通过／10失败2.36秒：pack_names内部tuple未经转换进入只允许真实JSON的canonical_input。修复为明确list／null，保留原JSON校验，不放宽shared serializer。修后新31项通过2.36秒。
- 新定位＋原WorktreeHeadLease组合112通过12.28秒；包括固定Git实际SHA-1／SHA-256的MAIN／LINKED／BARE／SEPARATE共八种布局。独立自有Job内创建临时仓库，linked来自真实已提交主仓库；bare／separate只是路径／配置向量，不冒充完整提交历史。
- 实际八布局均用原Location.config_source→PrivateConfigCopy→ConfigParseCommand参数→固定Git config --file --no-includes --null --list→既有白名单校验，核对预期bare／对象格式及原源摘要。调用测试工具是明确隔离向量，不是生产Native任意argv入口；生产白名单没有放开。
- 此后增加独立条目限额和输出读取中断保护，最终八文件208通过110.03秒：test_v20_windows_pipe_capture.py、test_v20_git_repository_location.py、test_v20_windows_worktree_heads.py、test_v20_git_config_command.py、test_v20_windows_native_process.py、test_v20_runtime_control_git.py、test_v20_runtime_guard_crash.py、test_v20_windows_stdio.py。
- 最终覆盖原文件／私有重叠／bidirectional／不支持标识／有界枚举、实际两格式与八布局；故障关闭及原owner保持；相邻有界输出／实际AsUser／Job／控制方退出保护及既有工作树回归。原生故障注入只作错误分支证据。
- backend/app 199文件Ruff格式通过；git_repository_location／windows_pipe_capture／windows_stdio／runtime_control_git四模块lint通过。源码及格式均同目录temp、flush／fsync、原字节核对和os.replace。旧stdio导入及嵌套with按锁定规则整理，没有关闭规则。
- 当前db20-r10 load_release仍实际通过，manifest db6f8e3cade6dc30d37c9902d90b7afeb7bc2b37ce60fc2e72e2758c7d7156e9。SOURCE_NAMES未改，未为无Schema／注册源变化制造新release。原r1—r10未覆盖。既有httpx提示未升级依赖。
- 没有前端源码变更，未机械重跑前端测试／构建／浏览器，也不借前批515／Chrome结果作本轮新证据。

## 边界与接续

仓库完整准入、固定只读元数据Native命令、有界输出到业务OperationStep／GitReceipt的生产消费、所有分支／对象闭包／metadata子树与完整worktree绑定、API01／02／03／04／71、REGISTER_BASE的原步骤仍待接。当前实际V2业务HTTP仍17条，完整仓库登记API未增加；不能从路径组件或上述八向量推断整仓库已准入。

未读取或改写正常用户仓库、正常data／.env.local，未启停用户服务、更新系统权限／网络策略或安装工具，没有真实模型／计数、V2提交／推送。临时Git仓库、JSON／源副本与进程均属于外层TemporaryDirectory和自有Job，结束后清理，仅保留本Markdown证据。

有界输出本轮独立结果与真实大输出／超限事实见[输出记录](control-git-output-2026-11-05.md)。下一单元先复核本Location与WorktreeHeadLease职责，完成剩余metadata安全前置，再扩固定类型的只读命令；不得把原参数tuple直接加入生产allowlist或用位置facts替代完整准入。
