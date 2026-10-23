# V1.5固定目标候选及请求详情实施细化

2026-10-22，目标V1.5；按正式1.0／EFFECTIVE增量实现，已合入后端OBJ-BATCH及AI-RESOURCE请求详情，不另立共同规格。冻结v9资源不变。

- BatchView补真实target_document_id与完整冻结source_refs，完成回执补DocumentEffect及实际采用建议ID；原current_document明确为批次固定目标。来源集合包含隐式长期需求，不误当只包含手动选项。EDITED之外禁止提供edited_content（含null）。
- 复用原SuggestionBatch、精确补丁、来源证明与CONTENT事务；取消ACTIVE／唯一CURRENT／旧FrozenFunction假设；五态人工业务状态不锁定批次。前端独立读取目标，阅读另一同版本文档不换写入目标。
- 新版model_calls沿原只读壳投影8个真实Wire分区、8项已保存计数及资源、selected／omitted；GET不重编译或调用计数。已知空分区显示未携带，缺失计数显示未记录；不把私有Canonical授权当已发送内容。
- C05评论原文和锚点去重，原评论改变后重试拒绝；C07同轮临时引用映射后绑定卡片，旧阶段未决项保留于真实关闭审计。
- 实施及离线结果分别见实现进度与verification/v1.5。合入文档不等于浏览器、真实供应方或版本验收完成。
