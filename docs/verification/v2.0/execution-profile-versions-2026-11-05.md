# 执行配置版本与原键接入（2026-11-05）

## 范围及依据

代码基线master／HEAD 28a7c9e，本轮V2源码未提交。依据BE0.17-draft-17／FE0.16-draft-16（DRAFT），完整补读OBJ-CODE-POLICY配置及ModelBinding／CommandDefinition、APP-CODE-SETUP与API07／13／21；沿用此前7.2、7.5.3—.5、7.7和FE设置／7.4读取。两份设计SHA256仍分别为1a8d277f25de570ce72e74a73ff763bf73f622fcf94b61f0820b78a1a5c6fd37及38557cee854697044ab7daba30f694738429be1235264a153851e8fc808cf3a7。未改正式设计或自动合并pending。

实际增加POST /api/v1/code-execution-profiles/{profile_id}/versions、GET同一路径及GET /api/v1/code-execution-profile-versions/{id}，原11条V2业务HTTP增至14条，另7个页面壳不计业务接入。复用原HTTP边界、幂等／回执／关闭和共享写事务，不新增执行操作或模型调用。

## 输入、输出及不变量

输入仅OBJ-CODE-POLICY十个客户端字段；父身份来自原路径，ID、版本和UTC时间由服务端生成。输出CREATED仅给EXECUTION_PROFILE_VERSION身份，读取给完整非秘密版本及实际未就绪原因；不把CREATED解释为运行准入。

execution_profile_content.py校验精确结构、固定执行器／Git／协议、两项显式CODE／COMPACTION模型绑定、既有Profile及辅助引用、22个正安全整数上限、输出上限和不超过300秒的交付窗口。复用ContentSelection／relative_content_path及原CommitIdentity／render_delivery_message：受管目录、内容路径和模式沿同一规则；交付消息只替换task_id／candidate_id，不允许预植程序交付trailer。消息换行在固定输入时统一，存储读取不悄悄修复。允许独立限制更严格，不额外发明文件／快照或输入／上下文上限公式。

execution_profile_resources.py在同一事务核对实际ModelPriceVersion行的Profile／快照／北京渠道／默认tier，且要求PRICE目录确实登记；模型准入引用须登记为Q20-MODEL。环境类型、应用秘密、网络目标、内容策略及证据引用均来自真实目录。整个executor／Git／CommandDefinition必须与登记值一致，浏览器不能改造参数数组。参数模板保存为有界JSON数据，不新增模板解释器或允许自由文字拼命令；具体参数语法由原不可变COMMAND资源负责。CODING配置只能关联CODING检查版本，并复用原检查投影核对真实依据／结构。

注册与准入分开：当前真实目录仍仅固定Git及三个既有模型身份，EXECUTOR／PRICE／CAPABILITY／CONTENT_POLICY等尚无真实登记项，因此未知引用拒绝。合法已登记但未就绪内容可固定为DRAFT；私有模型来源／UsageContract／账户价格与Token上界证据验证器尚未接入，程序保留Q20-MODEL、ready=false，即使目录标签声称ready也不据此证明模型能力。其他选中资源、检查版本的阻塞原因一并保留。本批没有制造可执行配置、价格、秘密、runner或供应方证据。

execution_profile_versions.py在原共享事务分配ExecutionProfileVersion全局ID及同父版本；容量拒绝不消费ID。父不存在和引用不匹配的原拒绝可按原键回放，资源目录故障明确Q20-CONFIG，不当作空目录或数据库故障。已成功原请求可直接回放，不重新读取目录。不可变JSON含重复键、额外字段、非法内容或需要换行修复时，读取返回存储错误且不回显内容。列表每页20，版本降序、真实越界空页及父不存在分开。

execution_profile_api.py、service.py及configuration_api.py接真实路径和V2错误契约；command_registry.py把C07原成功投影绑定EXECUTION_PROFILE_VERSION，identifiers.py增加原sequences枚举。影响source pin的修改另发db20-r9，manifest SHA256 1624a474220e6f8b93cfee7af03c93509e238e1b9a004afbe91e761d322f93a3，r1—r8未覆盖。只发布仓库资源，未升级正常数据库或部署服务。

前端code-execution-profiles.ts与WalleApi接完整Typed API、严格配置／就绪decoder、C07冻结字节和原结果decoder；原configurationRecovery增加C07 binding，复用已有持久owner和原键机制。嵌套参数副本不可变，保存恢复不新建key。无设置表单／页面变更，不把API测试写成UI完成。

## 实际检查

环境：Python3.13.5／固定SQLite3.54.1／Ruff0.17.3、Node24.15.0，前端使用既有锁定依赖。后端接口／发布维护使用普通非提升测试环境，经tools.quality_gate.environment专属临时根、tools/python-v20.py、tools/quality_python.py运行；未读取正常业务库、.env.local、供应商凭据或联网。

- 纯结构：python -B -X utf8 -m pytest backend/tests/code_tasks/test_execution_profile_content.py backend/tests/code_tasks/test_check_set_content.py -q -p no:cacheprovider --tb=short，283通过0.61秒。覆盖精确字段、全部限制、固定版本、模型别名／显式辅助、恶意路径、模板变量、重复引用、非法Unicode／非有限JSON和循环输入。
- 首轮隔离实际接口：test_execution_profile_versions.py，16通过96.88秒。后续补充分支后执行完整受影响回归。
- 最终五文件：test_execution_profile_versions.py、test_check_set_versions.py、test_v20_startup.py、test_v20_published_schema.py、test_v20_schema_release.py；52通过291.83秒。命令入口tools/python-v20.py tools/quality_python.py，-q -p no:cacheprovider --tb=short及专属--basetemp。含实际ASGI／共享事务、原成功／拒绝回放／关闭、并发唯一编号、21条分页与最新身份、实际DB价格关系、全部登记命令比对、CODING／TESTING隔离、容量、丢失提交ACK、坏存储、目录错误及退役HTTP lease。
- 测试专用catalogue／价格均在隔离测试夹具；mock资源不作为真实执行器、价格、模型或供应方准入证据。测试明确验证即使夹具目录全部ready，缺少私有模型证据验证仍不可执行。
- Node新专项10通过；npm test全套508通过8.24秒；npm run typecheck及npm run format:check通过。随后对消息模板空格式符及内容字节计数做契约对齐，受影响10项再次通过0.55秒、strict／format再次通过，不冒充整套重复运行。
- quality_gate隔离临时构建首次1.84秒，最终源码构建1.78秒通过；未覆盖frontend/dist，临时outDir清理。
- backend/app 194文件Ruff格式通过；四个新执行配置模块、配置API及command_registry lint通过。identifiers的既有两项lint基线见上一批记录，不称全仓库lint通过。初次新模块有列表转tuple／循环变量遮蔽及导入排序，已原子保存修复后检查通过；前端模板调整曾有未使用导入，已修正，strict未关闭。
- git diff --check与实际load_release db20-r9通过。httpx弃用提示保持既有依赖，不为消除提示升级。

源码及格式结果均先内存准备，再同目录临时文件flush／fsync、原字节复核及os.replace；未直接覆盖运行中的源码。测试与构建专属临时根及进程由各自工具清理，不留原始JSON／日志／录屏／截图。

## 尚未覆盖与后续

未增加真实浏览器到服务联调、C07浏览器IDB专项或页面状态／布局检查；Node HTTP是明确替身。未进行真实模型／计数、正常数据变更、用户服务更新、安装、ACL／网络策略修改或V2提交／推送。

完整设置UI、真实执行器／环境／COMMAND／价格和私有模型证据准入、AuthorizationGrant／任务配置应用、仓库完整准入及基线保留／内容捕获／秘密策略、Guard与受保护包／LPAC-WFP、Coding／Testing执行及交付仍在现行映射待推进。本批不是整版V2完成或供应方兼容验收。

接续补充：授权批已增加C07／C08／C15的真实Chrome＋IndexedDB原键恢复，见[授权及浏览器记录](authorizations-2026-11-05.md)。它不替代完整设置UI或真实浏览器到ASGI端到端验收；本记录中未执行的声明是本批当时边界。
