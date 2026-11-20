# V2.1前后端详细设计审查

日期：2026-11-14（Asia/Hong_Kong）。对象：前后端0.1-draft-1／DRAFT、大纲0.12及相关真实入口／浏览器恢复源码。仅静态设计审查，不修改两份设计，不执行产品／模型／计数、业务库、服务操作或提交推送。

结论：发现6项需修正事项（3项P1、3项P2）。当前不宜直接作为无歧义实施基线。模板章节／链接／编号齐全与业务契约正确是不同结论；此前静态输出记录保留其原检查范围，不作为本次语义审查通过证据。

## R21-01 [P1] 成果关联状态没有统一闭集或映射

位置：[后端298行](../../iterations/pending/v2.1/WALL-E.后端设计文档_V_2.1.md#obj-form-artifact)、后端1101／1132行；[前端400行](../../iterations/pending/v2.1/WALL-E.前端设计文档_V_2.1.md#5-页面与组件)。

对象允许CURRENT／NEEDS_REVIEW／REMOVED；存储与提交维护却生成CURRENT／STALE／REMOVED／UNVERIFIED，前端只定义后两种待复核显示。真实人工修改后，程序按7.2存STALE，按3.2的对象或公开DTO校验便非法；反向返回NEEDS_REVIEW时前端也没有明确映射。不是纯文案差异。

修正方向：统一业务枚举；如确需细分技术检查原因，将原因设独立字段并明确持久化／DTO／UI映射、全局待复核计数及Closure规则。验收需逐值跨越内容维护→存储→查询→显示。

## R21-02 [P1] 充分性判断把“不确定”与“尚未评估”混用

位置：[后端327行](../../iterations/pending/v2.1/WALL-E.后端设计文档_V_2.1.md#obj-form-assess)、后端1055行；前端400行。

AssessmentVerdict为SUFFICIENT／GAPS_REMAIN／UNCERTAIN，模型ASSESS_STEP却只接受SUFFICIENT／GAPS_REMAIN／UNASSESSED，前端也只给UNASSESSED文案。模型材料不足时无法输出对象认可的UNCERTAIN；如果改输出UNASSESSED又无法构造对象。assessment=null已经表达没有评估，不能把已评估但材料不足显示成从未评估。

修正方向：统一模型／对象／存储／读模型／UI的枚举；单独定义无评估、评估不确定、历史评估已陈旧。补“有评估但材料不足”与“从未评估”两个独立场景。

## R21-03 [P1] 路线卡采用与人工编辑的F校验没有分开

位置：[后端611行](../../iterations/pending/v2.1/WALL-E.后端设计文档_V_2.1.md#app-form-path)、655—656行、986／990—992行及A45／A55。

APP-FORM-PATH同时接人工编辑和不可变路线卡，准备／保存核实D/F/V；卡采用又直接调用它的COMMIT。但卡中冻结basis可能是F12，发布后已经F13，或之后仅切焦点成为F14；992行明确这些仍可采用，且不得改原basis。共用算法缺少明确的入口差异，照人工expected_formation_version严格比较会拒绝原本有效的卡；直接跳过所有F检查又会放松人工草稿保护。

修正方向：明确人工编辑使用expected_F的快照CAS，卡采用使用不可变冻结basis＋当前相关实体摘要校验；统一在最新实际图上做全局约束，并明确适配输入及事务内再次核实，禁止改写卡payload。A45／A55必须实际串入同一个COMMIT入口取证。

## R21-04 [P2] 原IndexedDB的旧标签页共存策略缺失

位置：[前端592行](../../iterations/pending/v2.1/WALL-E.前端设计文档_V_2.1.md#7-数据与技术依赖)、594—600行。

设计在同一DB version1／同一两仓库混存记录4与新FORMATION记录5，要求保留旧Coding／Testing恢复。只读原工作区command-recovery-store.ts::list（316行起）实际遍历同origin全部行，再按pendingSummary解析；command-recovery-model.ts当前严格要求schema_version=4。旧标签仍运行旧脚本时，新行5会让它报CORRUPT；物理版本不变也不会自动触发onversionchange使旧连接退出。升级新bundle的联合decoder不能改变已打开的旧脚本。

修正方向：补部署／旧标签兼容握手或连接版本切换策略，保证未知已发请求仍可查证；不能清空账本或默认旧标签全部已刷新。验收加入“旧bundle持有记录4，新bundle写记录5，旧标签核实原请求”的真实跨版本场景。本次没有运行该故障，结论来自现有解析路径与设计的静态推导。

## R21-05 [P2] 严格公开DTO仍存在未定义的嵌套结构

位置：后端926、1002—1009行；前端6.1严格解码规则。

后端声明所有命名结构拒绝未知字段，但PathPreview.affected_items／warnings、StepView.last_event及assessment摘要、relation页各kind的items仍只有概念名，没有字段／类型／null与联合形状；第3章也没有对应关系页值对象可直接复用。Summary无主线分支写goal/target=null，有主线分支又改用current_step_ref／active_branch_ref，target不是已定义字段。前端无法据此形成唯一严格decoder，后端和前端仍会自行猜字段。

修正方向：补齐上述DTO的完整嵌套字段与可空约定，明确Summary是否为exists判别联合及两分支完整键集合；给至少一个完整响应正例和关键反例。这里指出的是设计本身的结构缺口，不是要求本轮提前生成运行Schema／DDL。

## R21-06 [P2] 验收操作与其预期错配

位置：后端1184—1187行（TC-FORM-A05／A07／A08）。

A05要证明AI评估足够不改步骤，却只安排采用写卡再用户结束，缺少评估／建议应用后、用户点击前的观察。A07要证明ANALYSIS可无正文落地且不能替代CONTENT，却仍用含CONTENT的FBASE并安排问题／支线转交；没有分析来源及无正文对照。A08要证明成功补齐真实快照／缺省KEEP_OPEN／不受依赖门槛，却仅注入Closure保存失败，不能检查成功的完整Closure。

修正方向：逐行核对全部76项的前置、动作、断言是否真的证明预期；至少将以上补为独立成功／失败变体，不依赖简单复制相同预期文本作为覆盖证据。

## 保留结论及边界

共同对象／业务／模型／HTTP归后端，页面／组件／浏览器归前端的职责方向正确；未发现需要重开Q01—Q04产品决定的理由。完整源V2.0提交、可执行Schema／DDL／新资源、性能及供应商证据本来就是明确待办，未将“尚未实施”本身当作新缺陷。

本轮只新增审查记录及接续说明，六项均未修；没有改变设计状态或声称产品通过。修正后应重查共同类型、卡片采用真实调用链、跨版本恢复及验收场景覆盖。

审查输入原字节SHA256：后端`738e21dc4e21a30a412fc0977b6672dba007501c4bebd30d506637bfcec86c93`；前端`4e276d952b688ff73142fad73da6f5a06fca3cbf3fe793acce0e397d3af7d427`。两份设计在本轮保持不变。
