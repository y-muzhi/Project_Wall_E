# 固定对象原字节读取与图关联（2026-11-05）

## 依据和实现

HEAD28a7c9e／master，V2源码未提交。设计仍BE0.17-draft-17／FE0.16-draft-16（DRAFT），摘要沿[元数据记录](git-metadata-commands-2026-11-05.md)。本轮完整重读BE7.2.1—.6、7.7.1—.7及仓库对象／API01—05／71；不修改设计或合并pending。

git_object_read.py新增RepositoryObjectCommand，复用原挂起创建／调用者普通token／Journal／Job／Backend有界STDIO，Native只新增该精确类型。输入是已验证配置及原metadata／只读hooks、完整非零SHA-1／SHA-256 OID和commit／tree／blob类型；不接受HEAD、短ID、rev表达式、tag类型或自由argv。

Git的cat-file按请求类型可解引用对象，见[官方cat-file类型说明](https://git-scm.com/docs/git-cat-file)。因此完整EOF／exit0之后仍将类型、实际长度、NUL及原字节重新计算原格式OID，必须等于所请求的完整OID；真实tag→commit及commit→tree转换不能冒充指定对象。返回原字节、实际长度、SHA256，原字节repr隐藏；不转换编码／换行，不执行filters／textconv／mailmap，不联网补对象。hash计算分段更新，避免另拼完整正文副本。

git_repository_read.py从原MetadataCommand提取实际共用的原资源核对、固定仓库CLI、全新环境及hold／关闭；MetadataCommand仅保留两种查询／解码。没有为对象读取复制另一套资源或调度，旧解析命令及metadata Native摘要结构保留；新对象类型有独立固定环境策略及原参数事实。基类／派生任意类型和提取的原始tuple不获Native白名单许可。

git_object_graph.py仅从原字节已核验的对象提取CommitEdges／TreeEdge。再检查原类型、OID、长度及SHA，防伪造声明；commit保留原消息及扩展签名／encoding字节，解析唯一首tree、原顺序parents、author／committer边界及有界扩展header，不执行签名或解析用户身份。多父提交可读，不套用本系统新交付单父限制；不声称完整fsck身份／时间校验。

tree按20／32字节原OID二进制解码，严格完整记录及条目上限；使用Git目录按尾斜线比较的排序规则，依据[固定Git2.56.0 tree.c](https://github.com/git/git/blob/v2.56.0/tree.c)。只允许40000目录及100644／100755文件，拒绝symlink／gitlink／未知模式、零OID、缺项、重复、错序、无效UTF8、NFC／路径别名。复用ContentPathIndex与relative_content_path，不另造路径规则；空tree必须完整核验后得到真实空集合。解析器只返回当前树关联，不递归读取、不物化、不过滤掉不支持条目。

## 实际检查

普通非提升Windows用户，Python3.13.5／Ruff0.17.3／SQLite3.54.1／固定官方MinGit2.56.0.windows.4，工具依赖未改变。经tools.quality_gate.environment专属临时根，tools/python-v20.py tools/quality_python.py，-q -p no:cacheprovider --tb=short及专属--basetemp。

- 原字节对象读取接入后，13文件335通过235.93秒，退出0。范围为[元数据最终12文件](git-metadata-commands-2026-11-05.md)加backend/tests/code_tasks/test_git_object_read.py。包含共享资源抽取后完整Native／Registry／崩溃／STDIO／配置／原路径／worktree回归；纯对象类型／格式／空内容／二进制／OID错配／容量边界。
- 实际SHA-1／SHA-256两种仓库分别通过原受控进程读取commit、tree、blob；原Job为空后核对退出及输出。完整类型和OID、原字节长度及SHA256一致；对实际packed annotated tag请求commit，Git实际成功返回commit原字节，但本系统因类型／OID不一致拒绝。完整输出被替换字节后仍拒绝，不能把成功进程当真实内容。
- 随后补当前commit／tree结构解码，三文件专项78通过124.39秒，退出0。三文件为backend/tests/code_tasks/test_git_object_graph.py、test_git_object_read.py及backend/tests/infrastructure/test_v20_git_metadata_command.py。实际原生向量已改为生产解析器提取tree／blob关联；覆盖根／合并提交、多行签名／encoding header、二进制消息不转换、真实空tree／Git目录排序、截断／重复／错序／别名／非法模式／伪造原事实及独立限制。该专项40项图结构、32项原字节、6项原生组合；与前一335回归存在重叠，不相加作唯一测试总数。
- 启动该专项的第一次自动审批连接中断，命令未执行；经同一审批流程重试获准并运行，未扩大范围或绕过审批。本次78项为新增图解码后实际结果，不用此前335项替代。
- 最终backend/app206文件Ruff格式、12个本轮模块lint及git diff --check通过；load_release实际通过，仍db20-r10，manifest db6f8e3cade6dc30d37c9902d90b7afeb7bc2b37ce60fc2e72e2758c7d7156e9。SOURCE_NAMES没有变化，不制造新release。专项后.tmp/w2-catalogue-*实际为0，自有Job／测试进程已按原owner释放，无活动检查或测试JSON／捕获残留。
- 既有httpx／Starlette弃用提示1条，未改依赖。不改前端，未重复前端类型／构建／浏览器。

## 未完成边界

原字节hash及当前对象关联不证明其引用的其他对象存在、完整可读历史、基线全内容／秘密策略通过或仓库已准入。后续用同一固定对象命令有界读取完整关联，核对全部所需commit／tree／blob、根身份及内容路径／容量／秘密策略，再接原REPOSITORY OperationStep及REGISTER_BASE四步骤／保留引用／私有GitReceipt。API01—05／71没有新增，实际V2业务HTTP仍17条，runtime_admitted仍false。

无正常用户仓库／正常DB／.env.local、系统安装或既有ACL／网络策略改动，无真实模型／计数、用户服务启停、V2提交／推送。所有实际Git和JSON／输出字节均在本轮自有TemporaryDirectory／Job，结束后清理；最后只保留本Markdown记录。
