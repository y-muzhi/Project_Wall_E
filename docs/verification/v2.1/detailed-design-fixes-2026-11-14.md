# V2.1六项设计审查修正核对

日期：2026-11-14（Asia/Hong_Kong）。当前工作区codex/v2.1-design-review，代码HEAD21651c3。用户授权修正设计；实际只改pending设计与导航／计划／映射／断点及本记录，不实施产品。

[后端](../../iterations/pending/v2.1/WALL-E.后端设计文档_V_2.1.md)及[前端](../../iterations/pending/v2.1/WALL-E.前端设计文档_V_2.1.md)现为0.1-draft-2／DRAFT。输入大纲0.12和八份来源摘要不变。[旧审查](detailed-design-review-2026-11-14.md)保留0.1-draft-1原时点，不倒写旧结果。

| 条目 | 设计修正及接入位置 | 本轮核对／产品证据 |
| --- | --- | --- |
| R21-01 | 成果统一CURRENT/NEEDS_REVIEW/REMOVED；独立review_reason，补联合约束、计数及Closure规则；前端同义显示 | 对象、存储、提交维护、读投影、UI及R01场景静态对照；真实内容链路未执行 |
| R21-02 | 判断统一SUFFICIENT/GAPS_REMAIN/UNCERTAIN；null才是未评估；validity CURRENT/STALE及原因单独表达 | 模型／对象／存储／AssessmentView／UI对照；R02与FE16未执行 |
| R21-03 | 人工MANUAL_EDIT严格D/F/V；卡采用CARD_APPLY核实最新D及原卡相关binding，冻结F仅来源；共用事务内最新图算法 | APP-PATH／APPLY及A45/A55真实入口场景定义一致；无新增绕过参数，无产品接入证据 |
| R21-04 | 同名IndexedDB先DB1→DB2屏障，保留记录4，成功后才写5；blocked不发送，旧在途请求由新客户端按原key恢复 | 复核旧onversionchange／open(1)与新open(2)时序；FE15含旧连接／blocked／HTTP晚到／新客户端恢复，浏览器未运行 |
| R21-05 | Summary固定键集，补完整计数／来源／评估／事件摘要、RelationItem各联合、预览before/after及warnings、Closure读取；Artifact范围与预览影响独立分页 | 新完整Summary JSON可解析，类型及空值规则静态核对；补反例与R05／FE16；执行Schema／decoder未生成 |
| R21-06 | 逐行重读76项的前置／动作／期望并修依据；修A01—A05/A07/A08及非法夹具、跨步／NO_CHANGE／内容入口／提案分页／转交／卡版本／复核变体 | 76项独立预期仍与大纲逐条相同；动作校正包含成功观察点与独立失败分支，不能把文本相同当产品通过 |

## 实际静态检查

通过PowerShell内Python内存脚本解析两份八章、表格列数、重复显式锚点、示例JSON及A01—A76编号／预期，检查字段与入口策略、枚举正反例、DB2屏障及16项前端场景。核对大纲SHA256与八份来源原字节均不变。git diff --check退出0；backend／frontend／resources／docs/design／docs/templates的已跟踪差异为空。保存使用同目录临时文件、flush/fsync、并发原字节比较、权限保持与os.replace，临时文件清理。

本轮静态核对的通过范围是设计文本、来源保护及可解释的流程／契约一致性，不是运行时形式化证明。未执行产品测试、构建／格式化、业务库读写、IndexedDB升级、浏览器、真实模型／计数、资源准入、迁移、服务操作、Git提交推送。完整V2.0源、执行Schema／DDL／资源／decoder与实际供应商／负载证据仍按原技术待办取得。

结论：R21-01—06已在设计层修正并完成本轮静态复核，保持DRAFT／待审定，未自动正式合并或开始实现。

链接范围：38份当前Markdown、242条相对链接通过（包含历史验证但不改其正文）。

本次设计原字节SHA256：后端`602b5f824154114d679b027a6462509402c3ad9b017da133a1a7088728d813a8`；前端`de2fdfb2adafaaeab768b8f5c4ee9e4448e75ad72f5a32ea5d34c11bca5d68ea`。
