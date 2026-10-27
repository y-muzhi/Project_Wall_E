# 评论来源引用恢复修复专项 V1.5

2026-10-26，M15-COMMENT-01。代码已修复，70项相关后端／26项前端、类型及临时构建已验证；正式BE已合入。后续已获用户明确许可，空闲检查后后端8000／PID13012／PTY22018已加载修复，5项只读GET200。真实计数／Chat、用户业务记录写入及Git写操作均0，前端未重启。

## 1. 事件与正式依据

用户报告单条评论“让AI修改”显示“来源对象无效”。只读核对当前正常库，已保存run15评论材料的原始SourceRef为{kind:RUN_MATERIAL,guide_run_id:15,material_ref:comment_anchor}，同次选中清单的展示ref为r15:comment_anchor，原始SourceRef在selected.source_refs和alias中完整保留。该合法来源已进入讨论依据，原核实／捕获只按selected.ref等于material_ref查找，导致后续评论乃至普通讨论误报SOURCE_INVALID。

依据是正式BE OBJ-REQ SourceRef、C05／I34、AI-RESOURCE的确定别名及已携带材料规则，FE BND-DETAIL既有评论入口。FE修复前后均ccedbe7f…、仍1.0／EFFECTIVE；BE从e6e314ab…增量澄清OBJ-REQ来源读取，当前SHA256=5bbd4728ac854aef3aba327e1cb6854c1ce6315667b769e07fd3080672d8e50b。本次不是批量评论设计，不实现新的多选／批次入口；不改Prompt、Schema、Wire布局或发布新资源。

## 2. 最终修复

复用requirements/source_refs.py新增内部saved_run_material，verify_source_refs和guide/accepted_context.capture_source共同使用：仅从同需求真实run已保存ContextBasis.selected查找；允许精确selected.ref身份或RUN_MATERIAL选中项source_refs完整匹配原SourceRef，必须唯一且同ref的alias来源一致。不按前后缀猜ID，不从整个私有Canonical补读材料，不改历史快照或原评论。捕获继续核对原Wire摘要、严格Wire Schema，并只投影选中项实际携带的区块／消息／文本。

遗漏材料、映射歧义、外来需求／运行／Basis及alias不一致仍拒绝。已保存旧材料可读不授予当前评论写权限；新评论仍复核真实锚点、目标、两种版本及原文，已变动旧评论重试继续拒绝。两处前端入口文案按原设计改为“根据评论提出修改建议”，任务仍走PROPOSE_CHANGES／候选审阅，不直接覆盖正文。

实现文件：backend/app/requirements/source_refs.py、backend/app/guide/accepted_context.py；frontend/src/comments/panel.tsx、command-control.tsx。回归扩展原backend/tests/guide/test_v15_comment_guides.py，不另建平行来源服务。

## 3. 批次与实际验证

| 批次 | 交付 | 结果 |
| --- | --- | --- |
| C0定位／复现 | 正常库mode=ro只读原材料；私有Gateway执行首轮评论及合法进度，再发下一评论／讨论 | 修复前2个参数变体均SOURCE_INVALID失败／25.33秒 |
| C1修复 | 保存材料身份映射统一，原保护不删除；文案与原设计一致 | 已实现，既有数据无需修改 |
| C2回归 | 评论完整7项＋相关6文件63项；前端4文件26项；类型／临时生产构建 | 70后端／26前端全通过，完整结果见专项记录 |
| C3设计与交付 | BE来源读取澄清、实际证据、归档／映射／断点 | 文档完成；后续许可下后端加载及只读查询已完成 |

7项评论专项47.09秒；相关discussion／acceptance／context／cards／execution／comments 6文件63项287.10秒，均仅1条既有Starlette弃用提示。回归覆盖实际HTTP202及下一轮上下文、保存快照未变、孤立／版本／评论重试、遗漏／歧义／错run／跨需求及alias冲突拒绝。前端26项2054.0823ms、tsc和临时Vite构建退出0，仅原chunk提醒，临时输出自动清理、frontend/dist不变。

正常库原材料核实及捕获已只读通过；对两条当前未解决评论（安全ID3／4），在显式只读事务内按真实target／scope及讨论依据执行capture_inputs通过，total_changes=0。第一次诊断脚本未BEGIN，被原事务护栏拒绝，补只读BEGIN后通过；不是解除护栏。未调用业务命令、未新建run或用户消息，未执行真实Tokenization／Chat。

## 4. 合入与当前断点

已实际合入正式BE OBJ-REQ SourceRef段落；原AI-RESOURCE／Prompt／完整Schema源、模型资源和采用时摘要保持。FE正式文案原已明确，本次代码对齐，不改其文件。去向见[合并记录](../../merges/v1.5/合并记录-2026-10-26-评论来源恢复.md)，实际验证见[专项记录](../../../verification/v1.5/comment-source-reuse-2026-10-26.md)。

修复及检查完成后，按AGENTS第8节取得用户新授权，在无在途工作时正常关闭原后端15852，再用原库和安全助手启动后端13012／PTY22018，前端12440保持；5项只读GET200，不代用户点击AI或消费真实许可。原控制台Ctrl+C退出码1伴随完整shutdown日志，已核实端口释放及新启动，不当作强制终止。服务加载与整体人工语义、批量评论需求分开；后续接续先读当前实现进度，不重复跑旧真实槽或自动推送。
