<!-- 历史断点，来源 docs/project/v2.0/实现进度_V_2.0.md；保存2026-11-05；原字节SHA256 8224e04b027a898720416c3d8a8f920b5c458d9d9bf93727147e65378f6ed7da；当前断点见 ../../../project/v2.0/实现进度_V_2.0.md -->
# WALL-E V2.0实现进度

## 当前断点（2026-11-05，检查版本3条HTTP及Typed API已接；V2未完成）

- 目标与授权：持续完成V2全设计的代码及离线验证，不删减剩余目标。未授权真实模型／计数、正常库升级／数据变更、用户服务更新／系统安装及网络策略改变、V2提交／推送。V1.5本地提交28a7c9e已完成，无推送。
- 设计基线：BE0.17-draft-17／FE0.16-draft-16均DRAFT；SHA256分别1a8d277f25de570ce72e74a73ff763bf73f622fcf94b61f0820b78a1a5c6fd37及38557cee854697044ab7daba30f694738429be1235264a153851e8fc808cf3a7。枚举建议已获用户确认，pending独立迭代保留，不自动合入原设计；枚举DDL不等于权限业务API已完成。
- 阅读范围：根规则／版本导航／计划／映射；BE3章全部42组521字段、7.1／7.2／7.3／7.4／7.6／7.7完整规则、7.5.3—.5、4章固定步骤、APP-CODE-SETUP／CAPTURE及原键CLOSE／QUERY、6.1、全部API标题。API07—14／21—22及OBJ-CODE-POLICY配置子结构已完整补读，FE BND-CODE-SETTINGS完整补读；FE6.1／7.4已读。尚须按单元补读其他APP／6.2完整DTO、7.5其余／7.8—.9及其他前端页面；其余未完整读取的接口仍按单元补读；不将以前截断输出记全读。
- 环境：.venv Python3.13.5／Ruff0.17.3；本地固定SQLite3.54.1官方x64 DLL，tools/python-v20.py先激活再import SQLite，全局3.45.3未替换。Node实际24.15.0，依项目锁定TS／Prettier／Vite。未升级全局工具。
- 当前发布pin：db20-r8，manifest SHA256 b516926c3290c13d9cc8fc599cfee4dc2b69d4926fd31f6c24270e49d22f4c2d。当前source pin一致，实际发布／启动已验证；r1—r7保留，SOURCE_NAMES变动须另发新release；维护测试运行时不得编辑backend/app。
- 当前实际V2 HTTP为原键3条＋配置身份4条＋配置目录GET，加检查版本保存／详情／列表3条，合计11条；其余POST业务及完整设置UI未完成。不能据Schema或目录元数据宣布整版完成。
- 下一具体单元：执行配置版本API07／13／21，先完整复核OBJ-CODE-POLICY的executor／git／models／environment／commands／capture_rules／delivery／limits及模型价格／准入依赖，再实现结构与实际保存／查询／Typed API；不捏造模型快照／价格／runner。或按已完成后端接完整设置UI检查分区及新增C08真实浏览器恢复。完整仓库准入及基线／B1／B2继续原计划，未缩减。CheckSetVersion与C08已实现，不重新增加EntityKind或重复发r8。
- 实施提醒：元数据预检的普通ref文件若持有无DELETE共享句柄，会阻止自身后续Git原子更新；必须按原操作阶段管理捕获／释放，不能将全仓库元数据读锁保持到自身commit或把prepare后原Git自有.lock误当未知外部锁。原HeadLease／config原读锁及两次完整观察继续保留，合作窗口的ABA限制不变。此为下一单元的实现约束，尚未增加新模块。
- 接续命令：.venv/Scripts/python.exe -B -X utf8 tools/python-v20.py --probe；同启动器运行tools/quality_python.py，tools.quality_gate.environment配专属临时根。源码及格式结果必须同目录temp＋fsync＋原文并发核对＋os.replace；前端ts helper捕获old基线后调用，不能用format --write。仅必要受影响回归，不机械重跑全部。
- 数据与服务：未操作正常data／.env.local，未启停用户服务；本批仅隔离ASGI／数据库／维护副本、Node及临时构建检查，无新浏览器或真实模型／计数。自有检查进程与临时根已清理。常规启动仍为项目后端CLI／frontend npm run dev，本批未运行用户实例；真实调用／安装／网络策略许可不从历史继承。
- 本地文档排除：部分V2 design／project／pending在.git/info/exclude中，均实际落盘，未改ignore或强制暂存；未来经用户要求提交时须另核完整范围。检查证据仅docs/verification/v2.0的Markdown，正式资源／锁／Schema／来源清单不当垃圾删。

- 本轮完成及复用：完整worktree／原HEAD、严格类型私有配置解析原AsUser／Registry链路、严格GitReceipt及私有原句柄追加／恢复；原NativeReceipt已复用发布器，旧路径写入删除。全部实际位置／结果／缺口见[现行映射](../../../traceability/v2.0/需求实现映射_V_2.0.md)，详细断点见[本次归档](实现进度历史-2026-11-05-check-content_V_2.0.md)。这些组件已验证，不重复从头实现；生产仍只登记固定版本与私有配置解析，runtime_admitted=false。
- 剩余目标不删减：配置版本／真实资源与授权、完整仓库准入及业务操作、Git保留／内容捕获／秘密策略／seal、Guard认证Pipe与受保护包／LPAC-WFP、Coding／Testing任务／模型账务审计／检查与交付、全部前端页面及真实状态／空态／布局和完整联调。UNKNOWN权限禁止授权须接实际业务，不以DDL代替。真实供应方证据须另按精确次数／预算取得授权；目前未调用。


- 最新完整单元：check_set_versions.py／check_set_api.py及原configuration_api／service，API08／14／22的不可变保存、原事务／回执、实际父／quote／资源引用、版本唯一及DRAFT读取；前端code-check-sets.ts／WalleApi及原configurationRecovery已含C08。最终五文件回归60通过228.82秒；读取保护补充后新文件23通过85.87秒，目录原因细化单项通过4.65秒。前端498／strict／format通过、临时构建1.63秒，见[记录](../../../verification/v2.0/check-set-versions-2026-11-05.md)。无本单元半成品函数、活动测试或审批阻塞。
- 已修失败：首轮缺HTTP body_fields造成8项422，第二轮根对象序列化用于子数组造成5项500，已改实际入口和复用compact；quote夹具ID及前端readonly→JsonObject已修。新增重复键／存储规范化拒绝和目录失败真实Q20-CONFIG。正常资源目录仍无runner／case，未知引用不能发布，合法空／人工范围为未就绪DRAFT；ready算法正向仅内存夹具，非真实资源准入。
- 本批文件：上述后台两新模块、configuration_api.py／command_registry.py、identifiers.py／service.py及新Schema db20-r8；test_check_set_versions.py，frontend/src/api/code-check-sets.ts／code-configuration-identities.ts／walle.ts及新Node专项；对应验证／映射／本断点。正式设计和r1—r7资源未覆盖。当前未新增设置页面，未执行新浏览器／真实供应方或用户服务更新。
- 最新静态：190后端格式及新模块／登记lint通过；扩大到旧identifiers.py的2项基线lint仍未改，不能称全仓库lint通过。r8实际load_release与diff通过。当前端口5173／5174／8000无监听输出；仅本轮端口观察，不推断所有服务或在途任务。收尾40份文档链接均有效、diff／r8实际pin通过，测试及构建专属临时根为空。
