# 完整单元接续历史（非现行状态）

来源：docs/project/v2.0/实现进度_V_2.0.md；日期：2026-11-05；来源SHA256：a6553ec534da861c334bd85bafc8b4146d76ff1b58d8331651121269a938a95e。

此为增加提示并重定位链接的管理文档副本，不是原始字节备份。历史状态、计数及旧下一步保留追溯，不作为当前授权。现行接续见[当前断点](../../../project/v2.0/实现进度_V_2.0.md)，能力与证据见[映射](../../../traceability/v2.0/需求实现映射_V_2.0.md)。

---

# WALL-E V2.0实现进度

## 当前断点（2026-11-05，检查标准结构组件已验证，继续版本业务接入；V2未完成）

- 目标与授权：持续完成V2全设计的代码及离线验证，不删减剩余目标。未授权真实模型／计数、正常库升级／数据变更、用户服务更新／系统安装及网络策略改变、V2提交／推送。V1.5本地提交28a7c9e已完成，无推送。
- 设计基线：BE0.17-draft-17／FE0.16-draft-16均DRAFT；SHA256分别1a8d277f25de570ce72e74a73ff763bf73f622fcf94b61f0820b78a1a5c6fd37及38557cee854697044ab7daba30f694738429be1235264a153851e8fc808cf3a7。枚举建议已获用户确认，pending独立迭代保留，不自动合入原设计；枚举DDL不等于权限业务API已完成。
- 阅读范围：根规则／版本导航／计划／映射；BE3章全部42组521字段、7.1／7.2／7.3／7.4／7.6／7.7完整规则、7.5.3—.5、4章固定步骤、APP-CODE-SETUP／CAPTURE及原键CLOSE／QUERY、6.1、全部API标题。API07—14／21—22及OBJ-CODE-POLICY配置子结构已完整补读，FE BND-CODE-SETTINGS完整补读；FE6.1／7.4已读。尚须按单元补读其他APP／6.2完整DTO、7.5其余／7.8—.9及其他前端页面；其余未完整读取的接口仍按单元补读；不将以前截断输出记全读。
- 环境：.venv Python3.13.5／Ruff0.17.3；本地固定SQLite3.54.1官方x64 DLL，tools/python-v20.py先激活再import SQLite，全局3.45.3未替换。Node实际24.15.0，依项目锁定TS／Prettier／Vite。未升级全局工具。
- 当前发布pin：db20-r7，manifest SHA256 88dcb99509f6184f5289bffc403f6043130a43f9ada9fdb3f962c16604781860。当前source pin一致，实际发布／启动已验证；r1—r6保留，SOURCE_NAMES变动须另发新release；维护测试运行时不得编辑backend/app。
- 当前实际V2 HTTP为原键3条＋配置身份4条＋配置目录GET，合计8条；其余原48 POST业务及完整设置UI未完成。不能据Schema或目录元数据宣布整版完成。
- 现行实现位置、证据和能力缺口仅在[需求实现映射](../../../traceability/v2.0/需求实现映射_V_2.0.md)汇总；前序全部断点及失败过程见[本次归档](实现进度历史-2026-11-05-worktree_V_2.0.md)，历史命令和授权不续期。
- 最近完整单元：git_worktrees.py、git_ref_protocol.branch_namespace、windows_worktree_heads.py。完整worktree／直接分支解码，NTFS原根、linked双向指针和HEAD保持，拒绝prunable／检出目标／私有范围重叠／管理目录与原缺失项变化；关闭未知保留原owner。固定Git两格式真实组合及边界最终218通过9.05秒，183格式及受影响三模块lint通过，见[记录](../../../verification/v2.0/git-worktree-heads-2026-11-05.md)。默认环境硬链接夹具4失败已在普通环境补验；无本组件未完成函数／活动测试。
- 本轮涉及文件：上述三个产品模块，test_git_worktrees.py、test_v20_windows_worktree_heads.py、v20_git_vector_worker.py／test_content_manifest_git_vectors.py，以及对应验证／映射／本断点。原生组件不执行Git；生产Native目前登记固定--version及严格类型私有配置解析，runtime_admitted=false；verify_observation只接受原观察未改变，交付后单目标变化须另按Delivery处理。
- 最新完整单元：git_config_command.ConfigParseCommand已接原windows_native_process／runtime_control_git。固定私有副本argv／空global／非仓库cwd／新环境与原输入摘要，原copy／source借用保持到原根退出且Job为空；创建及恢复未知保留。受影响原生／登记／STDIO四文件63通过67.59秒，最终配置命令／源／副本／白名单四文件111通过24.63秒（含真实sha1／sha256），详见[记录](../../../verification/v2.0/native-config-command-2026-11-05.md)。夹具的Guard-self／重复关闭等待／sha256预期错误均已修；184格式／lint／diff及r7 pin通过，无本单元未完成函数或活动测试。
- 最新完整单元：git_receipts.py严格原绑定及允许facts、git_receipt_store.py原scope私有追加／原文件回读／未知只核对、windows_private_record.py原CREATE_NEW句柄无覆盖发布。runtime_control_git.py已复用同一发布器并移除旧路径MoveFileEx／unlink流程；原Native回执恢复不补丢失ACK／不建第二进程。六文件151通过54.93秒，补分支后四文件136通过33.02秒，187格式／四模块lint／diff／r7 pin通过，详见[记录](../../../verification/v2.0/git-receipt-store-2026-11-05.md)。无本单元未完成函数、活动测试或临时输出；Git业务生产方和原Step私有引用仍待接。
- 本批修改文件补充：git_config_command.py／windows_native_process.py／runtime_control_git.py、git_receipts.py／git_receipt_store.py／windows_private_record.py；test_v20_git_config_command.py／v20_stdio_worker.py、test_git_receipts.py／test_v20_git_receipt_store.py／test_v20_windows_private_record.py及原runtime_control_git专项。正式设计未合并改写；未提交V2。
- 最近完整单元补充：code_tasks/check_set_content.py及test_check_set_content.py，Coding／Testing共用严格三类标准／target／覆盖／引用结构、程序owner及不可变私有快照；74通过0.14秒，188格式／新模块lint通过，见[结构记录](../../../verification/v2.0/check-set-content-2026-11-05.md)。没有版本保存／查询／readiness或执行结果，未增加HTTP。APP-CODE-SETUP与7.6已完整补读；不存在本组件未完成函数或活动测试。
- 下一具体单元：先完整读APP-CODE-QUERY与非秘密读取模型，再接CheckSetVersion的API08／14／22及原事务／幂等／身份内唯一版本／CODING owner，不将结构通过当资源或真实依据通过。现有EntityKind缺CHECK_SET_VERSION；添加及C08原成功DTO将影响SOURCE_NAMES，需新发db20-r8并做原维护／启动回归；不得覆盖r7或在维护测试期间改backend/app。注册资源缺口必须如实返回／保存DRAFT，不能造runner或case ID／占位程序。配置版本／前端之后继续完整仓库准入、固定查询、真实GitReceipt业务生产者、原窗口／派发／后核对及B1／B2。
- 完整功能缺口：Guard认证Pipe／受保护运行包、LPAC／ACL／WFP／模型来源；Coding／Testing任务及配置版本／授权、真实资源、捕获／秘密策略／seal／保留、模型／计数预算审计、自检与交付、全部前端页面及空态／按钮／布局。未知权限动作禁止授权须接实际业务链路，不能以枚举CHECK代替。系统部署未授权不阻止继续源码与离线专项。
- 实施提醒：元数据预检的普通ref文件若持有无DELETE共享句柄，会阻止自身后续Git原子更新；必须按原操作阶段管理捕获／释放，不能将全仓库元数据读锁保持到自身commit或把prepare后原Git自有.lock误当未知外部锁。原HeadLease／config原读锁及两次完整观察继续保留，合作窗口的ABA限制不变。此为下一单元的实现约束，尚未增加新模块。
- 次级入口：配置API07／08／13／14／21／22已完整读，实施前还须完整读APP-CODE-QUERY及7.6的检查／覆盖适用性约束，接真实readiness和版本校验；frontend/src/application/router.ts尚未完整读并接V2页面。前序前端492／strict／格式及临时构建、Chrome存储／owner证据见映射，本批无前端改动，不改写成新浏览器结果。
- 大项未完成：全部Coding／Testing任务／执行器／问题权限／模型预算与审计／自检报告／交付、资源及配置版本／授权、内容捕获／秘密策略／seal／引用保留、前端逐页与空态／状态／布局、自有完整联调和真实供应方证据。未知权限动作禁止授权仍须在实际权限业务链路接入，不以枚举CHECK代替。
- 接续命令：.venv/Scripts/python.exe -B -X utf8 tools/python-v20.py --probe；同启动器运行tools/quality_python.py，tools.quality_gate.environment配专属临时根。源码及格式结果必须同目录temp＋fsync＋原文并发核对＋os.replace；前端ts helper捕获old基线后调用，不能用format --write。仅必要受影响回归，不机械重跑全部。
- 数据与服务：未操作正常data／.env.local，未启停用户服务；本轮ASGI／浏览器／Git全属隔离测试，已清理，不能称用户服务已更新。没有活动测试进程／浏览器／自有服务。后端CLI／前端npm run dev启动方式沿项目入口，本轮未启动用户实例；付费API许可不能从历史继承。
- 本地文档排除：部分V2 design／project／pending在.git/info/exclude中，均实际落盘，未改ignore或强制暂存；未来经用户要求提交时须另核完整范围。检查证据仅docs/verification/v2.0的Markdown，正式资源／锁／Schema／来源清单不当垃圾删。
- 环境：.venv Python3.13／Ruff0.17.3；原SQLite3.45.3保留。项目本地已固定3.54.1 Windows x64官方DLL及来源清单，tools/python-v20.py显式激活且早于sqlite3导入；未替换全局运行库。实际DLL摘要及检查详见构造记录。
