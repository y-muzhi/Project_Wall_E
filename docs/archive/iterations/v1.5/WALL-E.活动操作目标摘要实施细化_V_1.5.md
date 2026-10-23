# 活动操作目标摘要实施细化

2026-10-22，V1.5实施发现：RequirementDetail的active_operation只实现为type／id／文字摘要，人工草稿读取又要求显式document_id。重开页面、阅读B而编辑A时，客户端无法可靠找到真实会话目标；猜当前阅读对象违反目标绑定规则。

最终规则：active_operation安全摘要明确为`{type,id,summary,target_document_id}`。目标来自实际GuideRun／MANUAL_DRAFT／SuggestionBatch，同需求CURRENT；编辑和批次非null，AI讨论或生成新稿可null。摘要只提供读取定位，不授予写权限；所有正文命令仍复核目标／会话／版本。零文档仍可有无文档目标的AI操作。

影响：后端RequirementDetail读取及严格HTTP投影，前端严格解码及活动会话恢复，相关SQLite／HTTP与客户端专项。无新增实体、接口方法、数据库字段或模型调用。本轮按后端SHR-READ-MODELS及前端BND-DETAIL职责同步细化正式设计，版本状态不变；不作为产品验收证据。

本文件已按正式设计合入结果归档；合入位置见同版本merges记录，检查结果另记verification。
