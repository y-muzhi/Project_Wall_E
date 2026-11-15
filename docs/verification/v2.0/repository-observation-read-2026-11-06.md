# 原仓库观察读取与状态契约（2026-11-06）

## 范围与实现

HEAD28a7c9e／master，V2工作未提交。BE0.17-draft-17／FE0.16-draft-16保持DRAFT；SHA256分别1a8d277f25de570ce72e74a73ff763bf73f622fcf94b61f0820b78a1a5c6fd37、38557cee854697044ab7daba30f694738429be1235264a153851e8fc808cf3a7，本轮再次核对。依据OBJ-CODE-REPOSITORY、APP-CODE-QUERY原观察约定和API71，不新增RepositoryView字段或合并设计。实施偏差及范围保留[独立pending](../../iterations/pending/v2.0/WALL-E.Git历史读取与当前内容校验实施细化_V_2.0.md)。

新增backend/app/code_tasks/repository_observations.py，接现有service／handle_http／短读事务：
GET /api/v1/code-repositories/{repository_id}/observations/{observation_id}。同时按两个原ID定位，不fallback latest；同快照核对原仓库格式、真实资源Operation归属及无Task／Testing占位owner。完整投影原8字段；严格原OID格式、直接branch、JSON重复键、路径文字、UTC时间及READABLE关联，未知或不可用状态／null如实保留。缺失归属404，坏存储503，不以空数组／正常态修复或覆盖记录。GET不打开源文件句柄、扫描目录、运行Git、创建观察／操作或调用模型；本接口不是观察生产者／仓库登记完成。

前端新增api/code-repository-observations.ts及WalleApi.repositoryObservation：精确DTO／原ID／无分页／每入口错误白名单，非预期响应进入原只读未知错误。失败状态不改Readable，原字符串不规范化为另一对象。合法驱动器根与保留名边界单独检查；无新页面、IDB命令或自动refresh。

接入发现schema_v20.ENUMS的旧VERIFIED与现行READABLE／UNAVAILABLE／UNKNOWN不符，修正实现并发布db20-r11。随后按锁定Ruff整理该源文件import，发布最终db20-r12，manifest SHA256 0996b4ebc744f63b49c1b777970acd816911e216bdf3ca9c70fe446b86d0a310。r11／r12的fresh.v1.sql与upgrade-151.v1.sql实际字节相同；差异在不可变资源身份及源摘要。r1—r12均保留，不覆盖旧资源、不迁移现有200或正常151库。正常启动依旧严格核对当前200 pin，不通过启动自动修库。

## 实际检查

Python3.13.5／Ruff0.17.3／固定SQLite3.54.1、Node24.15.0及原锁定前端依赖。普通非提升隔离环境。后端通过tools.quality_gate.environment专属临时根及tools/python-v20.py tools/quality_python.py，-q -p no:cacheprovider --tb=short和专属--basetemp。所有数据库、维护包及JSON均为临时夹具；模拟记录生产只为读取测试，不作真实Git仓库登记证据。

- 后端首次四文件35通过1失败、21子场景通过（103.18秒）：新接口全部通过，旧schema构造检查只按legacy_guard_triggers()[:2]安装触发器，新增PROCESSING保留触发器后遗漏终态删除保护。这是检查夹具偏差，完整生产Schema已有保护；修改检查为安装实际fresh_sql完整结构，继续断言终态删除／改写／重新开启被拒绝，不放宽生产触发器。
- 修后五文件42通过、21子场景通过（117.85秒）：backend/tests/code_tasks/test_repository_observations.py及backend/tests/infrastructure/test_v20_schema_construction.py、test_v20_schema_release.py、test_v20_startup.py、test_v20_command_http.py。覆盖旧观察与新观察并存、两种OID格式、双ID归属、缺失／非法／额外参数／GET正文／幂等头拒绝、坏JSON／时间／路径／关联不虚报成功、READABLE可存且旧VERIFIED真实CHECK拒绝；GET前后无业务写入或模型派发。
- 最终r12三文件24通过（110.18秒）：test_repository_observations.py、test_v20_published_schema.py、test_v20_startup.py；后两者位于backend/tests/infrastructure。实际编译pin初始化／旧文档HTTP／新关闭控制、隔离非空151副本plan→rehearse→apply→只读核对，以及全新解释器固定SQLite激活／正常启动拒绝151均通过。维护测试期间backend/app冻结；不是正常用户库升级或TCP服务验证。
- 前端首次新4项2通过2失败：测试把ApiClient构造器误作options对象，实际为fetch函数；修正测试接入现有构造器，未改ApiClient。首轮全套519及strict／Prettier／临时构建通过。
- 补合法驱动器根和保留名边界后，strict发现split首项可能undefined；用具名worktreeComponent明确检查，不使用any／断言忽略。最终全套520通过（5.8秒），format1.95秒／typecheck1.11秒／临时Vite构建0.82秒通过。通过tools.quality_gate.commands／run_stage及quality_node.cjs隔离临时输出，没有改正式frontend/dist。
- 最终backend/app208文件Ruff格式，本轮repository_observations／git_commit_closure／git_object_graph／schema_v20／service五模块lint及git diff --check通过；当前load_release实际验证r12，r11与r12两个SQL资源逐字节相同。源码及格式均同目录temp、flush／fsync、原字节复核、os.replace。
- 后端复查一次因自动审批403技术失败未执行，经同一流程重试获准，范围未扩大、未绕过。现无待审批操作。既有httpx／Starlette提示1条，未升级依赖。

## 清理与未覆盖

最终.tmp/w2-catalogue-*与w2-front-observation-*实际均0，无活动测试、测试JSON／日志／构建残留。服务只读netstat对5173／5174／8000无匹配监听，不能推断其他服务；没有用户服务启停／更新。

实际V2业务HTTP由17增至18；7页壳保持。没有完整设置／仓库UI，未做本轮浏览器验收；Node替身响应不是浏览器到真实ASGI端到端证据。原历史读取真实进程证据另见[闭包记录](git-commit-closure-2026-11-06.md)，不把SQLite种子记录当Git生产结果。

仓库登记／refresh生产者、原OperationStep／GitReceipt、选定树完整内容／秘密策略与物化、REGISTER_BASE保留引用及四步骤仍待接；runtime_admitted=false。未改正常data／.env.local、用户仓库或既有ACL／网络策略，未安装或发真实模型／计数请求，未提交／推送V2。
