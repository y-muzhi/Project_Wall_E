# V2.0 worktree元数据与原生HEAD验证

日期：2026-11-05。代码为28a7c9e后的未提交V2工作区，依据BE0.17-draft-17／DRAFT的7.7.1／.2／.5。只操作本轮新建临时仓库和文件；无正常仓库写入、服务更新或真实模型／计数调用。

## 实现与不变量

git_worktrees.py有界解码成功查询的完整worktree list --porcelain -z和直接本地分支for-each-ref结果，保留bare、detached、locked、prunable及私有原因；字段重复、缺失、未知、非完整NUL终止、失败查询、非法OID均拒绝。branch_namespace复用原完整分支规则，核对全部父层级保守casefold别名及ref／目录冲突；不将内容路径NFC规则误用于Git分支。目标被任一HEAD检出返回TARGET_CHECKED_OUT，locked仍参与；任何prunable、分支symref或HEAD不一致均不能忽略。

windows_worktree_heads.py将原观察绑定到实际NTFS原目录、文件ID和只读HEAD数据句柄。复用LocalPathGuard／LockedConfigSource，不另建权限或读取流程。普通.git目录／主gitfile及正常linked worktree逐项核对；linked限定common/worktrees直接子目录，commondir解析后须同一原common，gitdir反向指针须回到同一个原.git文件。HEAD只允许完整非零detached OID或一次指向直接本地分支；bare的合法未出生HEAD只作元数据，不认作被检出分支。

私有范围与源目录按实际规范路径双向排斥；不以字符串清单或resolve充当原生身份。所有句柄先计入限额；目录及探测元数据检查特殊属性，数据字节有界、原始UTF8及摘要保持。config.worktree存在拒绝；缺失元数据必须是真实not-found，其他错误不得当空。完整common/worktrees直属管理目录集合与清单逐一匹配，缺项或新项拒绝。verify重新检查原身份、特殊属性、原HEAD／指针数据、原缺失项及管理目录；verify_observation同时要求新Git完整观察与原观察一致，不自动采用变化。

构造或清理失败保留原owner；数据、元数据探测、目录分阶段关闭，未知时不释放后层保护，不按路径重新打开或删除。生成仅内部指纹，不导出路径／原始指针／锁原因。此组件不执行Git，不是完整仓库资格、交付窗口或跨程序全库锁；外部ABA限制仍适用。

Git porcelain-z属性／多行原因及gitfile、commondir、linked反向指针规则依据官方文档，并由下述固定Git实测区分兼容证据：[worktree文档](https://git-scm.com/docs/git-worktree)、[仓库布局文档](https://git-scm.com/docs/gitrepository-layout)。

## 实际检查

Python3.13.5／SQLite3.54.1／Ruff0.17.3；tools.quality_gate.environment与tools/quality_python.py限定本轮自动清理的.tmp根、隔离数据和禁止外网。通过tools/python-v20.py调用，pytest禁用缓存。

- 重构后纯worktree＋引用协议：137通过，0.19秒。
- 初版原生65＋上述137：202通过，2.40秒；加入真实固定Git：203通过，8.35秒。
- 补充属性复核、硬链接、逐级关闭失败／内层owner保留、管理目录新增和缺失根后，默认隔离环境213通过／4失败，3.48秒。4失败均在创建硬链接夹具时WinError5，尚未进入产品代码；不称产品路径验证通过。
- 最终普通Windows环境四文件：218通过，9.05秒（原生80＋元数据47＋原引用协议90＋双格式实际Git组合1）。命令文件：backend/tests/infrastructure/test_v20_windows_worktree_heads.py、backend/tests/code_tasks/test_git_worktrees.py、test_git_ref_protocol.py、test_content_manifest_git_vectors.py；参数-q -p no:cacheprovider --tb=short --basetemp <本轮临时目录>/p。既有httpx弃用提示保留，未安装或更改依赖。
- 独立worker不导入产品解析器，使用固定MinGit2.56.0.windows.4，在自有Job里新建sha1／sha256 bare、attached／detached linked worktree、实际locked（含多行原因）和prunable记录。验证全直接分支、HEAD关联、目标占用、symref拒绝。随后仅精确清理新建missing夹具的管理目录并重新查询证明原健康三项恢复；这是新测试数据重配，产品无prune／修复逻辑。原生消费者绑定实际三项HEAD并重验指纹。
- 实际元数据包含普通主目录、独立主gitfile、bare未出生HEAD、linked双向指针；真实共享写入冲突、原根不能替换／改名、四类元数据硬链接拒绝。注入失败只用于原生属性／清理错误分支，不冒充外部真实崩溃。
- backend/app 183文件格式通过，新增／受影响三个模块lint通过。未修改前端，不重复浏览器或构建检查。

全部本轮worker／Git孩子已退出且原Job为空，临时库、元数据、JSON及原始输出均随专属临时根清理。未操作正常data或用户服务。最终diff及资源pin检查见当前进度，后续补充另记。

## 未覆盖

生产Native当前仍只登记--version；完整受控命令、仓库配置／.lock／对象闭包准入、MAY栅栏与原窗口、私有GitReceipt、交付后目标变化核对及实际业务入口尚待接。当前verify_observation仅支持原观察不变；交付后允许的单个原目标变化应由原Delivery事实与后核对单独实现，不能借此组件放行任意变化。没有运行真实业务交付或证明Q20-GIT／整个V2验收。
