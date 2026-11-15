# V2.0检查标准版本实际接口与前端绑定

日期：2026-11-05（Asia/Hong_Kong）。代码为28a7c9e之后未提交V2工作区。依据BE0.17-draft-17／FE0.16-draft-16：OBJ-CODE-POLICY、APP-CODE-SETUP、APP-CODE-QUERY公共读取规则及配置非秘密投影、API08／14／22、7.6和BND-CODE-SETTINGS。正式设计未改写，未操作正常数据／服务／凭据或真实供应方。

## 实际接入

新增POST /api/v1/code-check-sets/{check_set_id}/versions、GET同一路径、GET /api/v1/code-check-set-versions/{id}，复用原HTTP边界、事务、幂等账本和原成功DTO／回执／关闭。新增版本不创建任务／Operation、不执行检查／模型、不更换旧任务依据。当前V2业务HTTP由8条增至11条；另7个页面壳不计为业务API。

保存使用上一批CheckSetContent，不接收客户端owner／ID／版本／就绪或结果。父身份及真实Revision归属和quote在同一写事务核对；不存在的runner／命令／案例／运行时引用拒绝，不制造占位资源。已登记但未准入内容可保存DRAFT；空检查／人工范围不推断无需检查或ready。全局CheckSetVersion ID复用sequences，版本在同父身份全部owner内递增唯一，公共入口只写CODING。容量耗尽明确PRECONDITION_FAILED并不消费新ID。

读取在同一快照中核对原父关系、严格内容及真实依据，附实际ready／unresolved_capability_codes。资源与受控能力、required完整性及Testing功能要求分别计算；当前真实目录无runner／案例，不能运行。保留原版本顺序及全部owner，不把旧TESTING版本转换成CODING；Coding采用资格另由实际配置／任务链核对。合法空页与父不存在、存储／目录错误分开。重复JSON键、缺字段、非法内容和会被规范化的损坏存储拒绝，不静默重写成有效版本。

配置目录读取失败不作“没有资源”，保存返回503并给Q20-CONFIG原因，不误报数据库；原已接收请求可直接回放，不因重新准备资源产生新版本。未知提交ACK仍查原键，不分配第二个版本。service动态路径参与原V2错误契约，未新增通用catch-all。

前端code-check-sets.ts、WalleApi接三条实际方法，完整结构／条件null／owner阶段／覆盖校验，C08仅接受201及CHECK_SET_VERSION结果。原配置CommandRecovery增加C08原输入／结果binding，复用冻结字节／key、IDB事务owner和关闭机制。Readonly内容经原snapshotObject转换并冻结，未以any或关闭strict通过。这里无设置表单、页面路由或新DOM交互，不称UI完成。

## 资源发布与检查

EntityKind.CHECK_SET_VERSION、service及C08成功DTO修改影响SOURCE_NAMES，另发db20-r8，manifest SHA256 b516926c3290c13d9cc8fc599cfee4dc2b69d4926fd31f6c24270e49d22f4c2d；r1—r7未覆盖。固定SQLite3.54.1、Python3.13.5、Ruff0.17.3／Node24.15.0及项目锁定前端依赖。新资源仅仓库文件发布，不是用户库升级或服务部署。

本轮Python均使用tools.quality_gate.environment创建专属.tmp根，通过tools/python-v20.py启动tools/quality_python.py，-q -p no:cacheprovider --tb=short及专属--basetemp，阻断外网／正常数据／凭据。ASGI／并发／维护测试在普通非提升非AppContainer测试环境运行。

- 首轮新HTTP＋原结构83通过／8失败65.11秒：实际请求模型缺body_fields声明，正文被原空体门禁拒绝。修复入口声明；另修正依据夹具RevisionID。
- 第二轮17项12通过／5失败65.55秒：子数组误用只接受根对象的canonical_input。改复用schema_transport.compact序列化已校验固定数组；未放宽根对象校验。修后真实保存／原回放／查询单项通过5.05秒。
- 新版本／旧配置身份／默认启动／真实发布维护／release五文件60通过228.82秒：test_check_set_versions.py、test_configuration_identities.py、test_v20_startup.py、test_v20_published_schema.py、test_v20_schema_release.py。维护只操作隔离副本，不是正常库升级。
- 随后补充读取重复键／不允许规范化存储的拒绝，完整新版本文件23通过85.87秒。目录故障能力原因细化后，仅受影响单项再通过4.65秒。前面60项是细化前组合，不冒充最后所有代码一次全量。
- 包含真实同事务版本与回执、原键冲突／关闭、父不存在拒绝持久化、Revision实际quote、未知资源拒绝、并发版本号、混合历史owner、容量、未知提交及坏存储。资源ready=true仅为纯算法的内存事实夹具，不称已准备runner／供应方或原生检查器。
- 前端新增及受影响13项通过；全套npm test 498通过，7.28秒；npm run typecheck及npm run format:check通过。初次strict发现readonly数组不能直接作为JsonObject，改用原snapshotObject，未使用类型绕过。
- 质量门禁的隔离临时生产构建通过1.63秒：tools.quality_gate的environment／commands(build)／run_stage，仅临时outDir，结束清理，未覆盖frontend/dist。
- backend/app 190文件格式通过。新check_set_api／check_set_versions和配置API／登记模块lint通过；扩大检查时identifiers.py报告导入排序及原entity_id ValueError的TRY004两项，已与HEAD核对为既有基线，未修改无关异常语义／为此覆盖已发布pin，不将扩大lint称全通过。
- git diff --check及实际db20-r8 load_release通过。既有httpx弃用提示保留，依赖未升级。

本轮观察5173／5174／8000无监听输出；只表述这些端口当时状态，未启停用户服务。所有测试临时库／JSON／私有维护包、构建产物和测试进程由各自专属根清理，未留原始报告／日志。没有新增浏览器或真实模型／计数证据。

## 未完成

完整代码设置UI、C08的新增实际浏览器交互／IDB组合尚未验证；前端HTTP在Node检查中是明确替身，不称浏览器到真实服务联调。执行配置API07／13／21、真实runner／case／环境／fixture准备与准入、授权／任务配置应用、完整检查执行及其余V2业务仍待推进。版本CREATED只说明本地记录已保存，不能称可执行或完成2.0。

检查版本结构及已有P2／原生／Git回执基础不重复重建。完整目标／剩余项见现行映射与当前断点；不因本批通过缩减原B1／B2／前端与收口目标。

收尾：40份本轮验证／映射／断点／计划及项目历史Markdown的本地链接均有效；设计两份SHA保持基线，db20-r8实际pin、190文件格式／四个受影响代码模块lint和diff通过，测试与构建专属临时根为空。
