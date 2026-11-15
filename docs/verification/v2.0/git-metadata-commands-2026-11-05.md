# 固定Git元数据命令及原文件绑定（2026-11-05）

## 依据与边界

master／HEAD28a7c9e，V2工作未提交。BE0.17-draft-17／FE0.16-draft-16均DRAFT，SHA256分别1a8d277f25de570ce72e74a73ff763bf73f622fcf94b61f0820b78a1a5c6fd37、38557cee854697044ab7daba30f694738429be1235264a153851e8fc808cf3a7，本轮复核未变。完整重读BE7.7.1—.7；按既有固定工具／配置／元数据规则实施，不改变产品要求、不合并pending。

输入为原RepositoryLocationLease、原私有配置副本及真实解析结果、原metadata树、私有只读空hooks目录和明确查询种类。输出为既有LocalBranch／Worktree解码结果；实际原生组合再由既有WorktreeHeadLease核对全部工作树／HEAD双向身份。没有新增业务HTTP，当前仍17条；不是完整仓库准入、历史闭包或仓库登记完成。

## 实现与不变量

- windows_empty_directory.py仅为本操作新建直属子目录设置受保护DACL；不改变已有目录ACL。实际调用者及OWNER_RIGHTS均只读／执行（0x1200A9）；OWNER_RIGHTS用于限制所有者隐含WRITE_DAC，依据[Microsoft SID说明](https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/manage/understand-security-identifiers)。原FileID／安全描述摘要／空内容持续复核，hold期间拒绝关闭。LIST_DIRECTORY原句柄无DELETE共享，保持目录路径；部分失败保留原owner及句柄，重试只清理。
- git_ref_metadata.py严格解码files后端packed／loose refs：有界原字节、完整40／64位非零OID、精确LF／UTF8、全ref语法、重复及分支别名冲突、heads symref／replace拒绝；允许非head远端符号引用及合法tag peeled记录。读取优先级与[Git refs布局](https://git-scm.com/docs/gitrepository-layout)一致，loose覆写同名packed值，不将两个来源误作重复分支。
- git_repository_metadata.py持有原Location，遍历common metadata子树，所有节点原NTFS身份／属性、数据读句柄及目录集合保持；refs／packed原正文有界固定，真实全head集合确定排序。条目／原生句柄／文件字节／总记录分别限额，拒绝重定向、硬链接及不支持属性，foreign worktree配置／promisor不忽略；记录发现的.lock供后续写入前拒绝，不删除。此处不是对象可读历史证明。
- git_config_command.py复用真实ConfigParseCommand输出，有界完整EOF／原scope／UUIDv4 nonce／实际字节数／零退出／空stderr校验后，核对原副本与Location源FileID／SHA、实际bare及既有全部配置白名单。对象格式由实际extensions.objectformat或Git的SHA-1缺省推导；结果不可改绑，不改变原解析命令Native输入摘要。
- windows_pipe_capture.py抽出require_complete_output供上述可信后端调用方统一检查。该函数不是可对外提交的进程证明；原scope／nonce／exit必须来自实际Native owner，不能据构造dataclass声称运行过。
- git_metadata_command.py只允许固定WORKTREES／LOCAL_BRANCHES两类。固定worktree list --porcelain -z、for-each-ref的refname／objectname／objecttype／symref NUL格式；绝对gitdir／worktree及实际safe.directory、只读空hooks、禁fsmonitor／gc／maintenance／protocol。环境复用原私有配置命令的全新白名单，不继承GIT_DIR／注入／代理。原始argv tuple仍拒绝。
- windows_native_process.py／runtime_control_git.py在原普通调用者token、挂起创建、Journal、原Job及独立STDIO链路中接入该精确命令类型；无第二套调度器／自由shell。资源借用持续到原Job观察为空，清理不因元数据后核对异常再次消费同一context；异常时已实际借出的各计数均归还，owner只允许原清理。
- metadata读句柄会阻止自身未来ref原子写入，后续必须按阶段释放metadata lease再写入；Location／配置／Head依据各自阶段保留。此组件不消除外部新增／ABA，不证明全仓库冻结。

## 实际检查

环境：普通非提升Windows用户，.venv Python3.13.5／Ruff0.17.3、固定SQLite3.54.1、官方固定MinGit2.56.0.windows.4；工具及依赖未升级。默认受限环境不具备这些原生向量能力，使用经批准的普通测试环境。一次工具自动审批返回403技术失败，命令未执行；相同隔离只读检查重试获准并执行，无尚待批准事项。

经tools.quality_gate.environment专属TemporaryDirectory，tools/python-v20.py tools/quality_python.py，-q -p no:cacheprovider --tb=short及专属--basetemp。本轮临时仓库／配置／输出／进程属于测试，不访问正常业务仓库。

- 只读目录首轮9通过1失败（1.14秒）：仅属性句柄没有实际阻止目录rename。增加LIST_DIRECTORY数据读句柄，修后10通过（1.04秒）；实际最大有效权为只读／执行，创建子文件／子目录及持有期间rename被拒绝，关闭后由私有父目录合法清理。没有将该局部修复写成所有旧LocalPathGuard均已提供数据共享保护。
- 元数据及既有配置专项77通过（1.77秒）；随后增加完整输出绑定／真实格式推导边界。首轮新Native命令4通过（60.26秒）。
- 完整回归首次工具回执未保留，核实无对应活动进程／临时目录后重跑取得下列结果；不把未知回执填写为通过。
- 最终12文件301通过，170.16秒，退出0：
  test_v20_git_repository_metadata.py、test_v20_windows_empty_directory.py、test_v20_git_metadata_command.py、test_v20_windows_pipe_capture.py、test_v20_git_repository_location.py、test_v20_windows_worktree_heads.py、test_v20_git_config_command.py、test_v20_windows_native_process.py、test_v20_runtime_control_git.py、test_v20_runtime_guard_crash.py、test_v20_windows_stdio.py、backend/tests/code_tasks/test_git_local_config.py。前11文件均位于backend/tests/infrastructure。
- 实际SHA-1／SHA-256原仓库含packed／loose三个head、合法tag peeled／远端符号引用及detached linked worktree。配置解析、两个查询分别经实际AsUser／原Job／Registry／独立Backend有界读取，核对进程退出和Job为空，再解码完整输出，最终WorktreeHeadLease核对两个工作树。测试fixture独立peer允许实际不同LaunchScope；不修改生产协议。
- 覆盖异常EOF／超限／stderr／错误nonce／原scope／布尔或非零退出、元数据集合变化、关闭失败保留及原借用计数归还、未知不能作成功。故障注入只证明相应分支，不冒充掉电或安装Guard验收。
- backend/app 203文件Ruff格式检查通过；本轮九个模块lint通过，未关闭规则。源码／格式结果均内存准备、同目录temp、flush／fsync、原字节复核及os.replace。
- load_release实际通过，仍db20-r10／manifest db6f8e3cade6dc30d37c9902d90b7afeb7bc2b37ce60fc2e72e2758c7d7156e9；SOURCE_NAMES没有变化，未制造新release或改旧资源。既有httpx／Starlette弃用提示1条，未升级依赖。
- 无前端源码改动，未机械重复前端类型／格式／构建／浏览器；历史515项和Chrome证据不是本轮新结果。

## 未覆盖与接续

仍需固定cat-file等对象／完整历史读取、非空仓库准入、仓库业务OperationStep／原GitReceipt事实生产及API01／02／03／04／71接入；随后REGISTER_BASE四步骤及原保留引用。runtime_admitted仍false，未安装Guard／认证Pipe／受保护宿主或实现LPAC-WFP，未扩TASK授权。

未改正常data／.env.local、用户仓库或现有ACL；未启停用户服务、系统安装／策略更新、真实模型／计数、V2提交／推送。临时JSON／源副本／捕获字节仅属于TemporaryDirectory，自有Job先终止并清理；检查结束无本轮临时根或活动测试残留。仅保留本Markdown汇总。服务监听观察与最终diff检查见[现行断点](../../project/v2.0/实现进度_V_2.0.md)。
