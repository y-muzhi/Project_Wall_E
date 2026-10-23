# V1.5执行快照与读取投影实施细化

2026-10-22，正式设计1.0／EFFECTIVE内实施细化；不新增第三份共同规格，不修改冻结resources/v9。

接受快照与实际装配ContextBasis分开；Canonical保留固定候选，ContextBasis保存每次候选实际selected／omitted；不重查扩大历史。审计只在严格Schema验证的私有业务authorization路径保留授权，HTTP认证仍剔除，精确请求不能安全留存时不发送。

RunView增加明确progress_error，未提交的应用／进度结果为null，终态显式分类；尚无实际请求的材料统计为null。取消后已完成返回实际RunView；重试新建关联run并复用原话，版本冲突不静默改绑。

已合入后端AI-CONTEXT-BASIS及SHR-READ-MODELS。此记录不代表C05／C06、全部正文／卡片／供应方验收完成；实际证据见本版context-execution及ai-acceptance验证。
