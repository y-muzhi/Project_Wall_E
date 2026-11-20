# V2.1路线预览（2026-11-16）

环境：隔离a0f4059＋未提交代码，core/r52、Schema210/r3；无真实模型/计数、用户服务/正常库操作。

新增preview_contracts、preview_projection、preview_queries及formation/api.py真实POST path-preview。复用原load_input/prepare_route和verify_links，在只读事务完整校验D/F/V、图、临时符号、来源和区块；不预分配Step/Result/Artifact、消息或事件。确认提交仍走原PATCH重新核实全部状态。

影响与提示各按ordinal分页，上限100，当前页保持真实total。游标固定文档、区域、原完整业务输入及D/F/V；输入/状态改变PATH_CHANGED，不产生授权token。105原步骤前插新步骤及改Goal得到107影响、106提示；两区域可分别翻完，另一域回首页，临时标签不含resolved_ref。LINK_CONTENT只展示真实核实的ARTIFACT_LINK，不建Artifact；源区块无效或循环整批拒绝。

检查：test_v21_path_preview.py及完整用户结束1项合计8 passed，28.56秒。覆盖所有影响/提示分页、空变化、实际来源、预览后实际提交、循环、陈旧游标、无key HTTP、未知私有字段、错误分页与严格输出。预览前后完整业务/序列快照不变、0 GuideRun/LLMUse。Closure/Preview共享current_artifact_matches，不建立第二套正文匹配规则；共享抽取后另补真实含关联的Closure／正文变更定向检查：1 passed，8.92秒；保持原Closure及结束状态。

命令使用quality_python.py与固定runtime、quality_gate.environment离线保护、no:cacheprovider和独占临时目录，临时DB/日志均已清理。不是生产服务、前端或新AI发布/采用验证。
