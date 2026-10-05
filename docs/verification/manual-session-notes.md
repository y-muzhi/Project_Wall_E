# 实际人工编辑会话生命周期单元

本批于用户本地日期2026-10-06保存；原始报告文件名和内部时间保持实际UTC，不改写。`documents/manual-session.ts`拥有实际RequirementEditor、Autosave、Recovery、End和IndexedDB，一个由完整详情读取得到的真正MANUAL对象只对应一个会话。父级需保留它经过窄屏、失败读取和离开确认；本批没有把诊断父级当完整产品路由。

编辑器有效性、来源选区和错误由实际事件发布；真实失焦及页面hidden触发保存，core状态同步readonly。窄屏/离开调用先同步冻结，再形成并保存实际最新完整配对；组合未完成不能提交旧配对并称作本次内容已保存。恢复支持宽度后，父级取得完整实际详情再调用revalidate，只有CURRENT完全保持且草稿等于本会话真正确认对象才可继续，不从GET虚构保存回执、替换本地账本或覆盖本地内容。外部推进版本保持原内容/账本并锁定，不能用“继续编辑”绕过已知READ_CONFLICT。

prepareLeave返回实际保存确认与单独的本地保护结果，未保存时核对真正已提交IndexedDB里的完整配对/修订号；部分组合输入不能声称全被保护。继续编辑仅适用于可继续的离开状态。retire不取消业务、不删除未知草稿：先退休观察/恢复/结束控制器，等所属保存，然后等真实IndexedDB打开/事务settle，最后销毁解析上下文与关闭连接；相同retire共享Promise。恢复存储不足的提醒继续后仍可见，详情读取错误文案不会推翻已经确认的结束结果。

`recovery-store.ts`跟踪实际事务Promise，包含尚在open的阶段，settle只等待不删除、不把容量/可用性失败当保护成功。Autosave提供冻结的真正confirmedDocument供版本/完整对象核对，不采用缓存或GET当保存成功。

最终 [117 Node/完整TS/依赖](frontend-2026-10-05T15-20-46-775Z.json)120输入hash保持；[实际API/浏览器/SQLite全链](api-browser-2026-10-05T15-20-45-138Z.json)345输入hash保持、前序三种真实控件/全部链保持，新增：

- actual manual session/本地库，输入后同步窄屏锁，真正I11草稿v2并原会话复核恢复；CURRENT保持v4。
- 实际编辑器组合生命周期与事务，未完成组合离开返回saved=false/local_protected=false；继续并结束组合后真正I11 v3。此为synthetic composition，不是Windows IME验收。
- 真正另一页I11使草稿v4，原会话账本仍3/对象保持、READ_CONFLICT冻结，离开保存/继续不能绕过锁定。
- 真正新会话v4输入，原生I11已成功v5但回执本地丢弃，原生I10复查200再丢弃；UNKNOWN离开返回saved=false/local_protected=true，不猜失败或清缓存。
- 冷IndexedDB实际put立即settle验证打开阶段受保护；原会话retire等待任务并清DOM，再以新实际解析器/同名数据库重开，实际v5和保留本地base4进入COMPARE，拒绝自动采用。
- 真正取消确认协调器I13清理后root IDLE/CURRENT全文和v4保持；最终24需求/24文档/4版本/2评论/28Run/LLMUse0，自有服务正常关闭、Vite关闭前存活/代理200，无付费模型调用。

新增生命周期路径使用显式诊断时钟隔离既有2秒/10秒测试，不用内存替代HTTP/SQLite/IndexedDB。全链通过后没有无理由重复后端730历史检查。缓存runtime变化后 [编辑器来源回执专项](editor-browser-2026-10-05T16-49-22-851Z.json)70hash/16真实SQLite回执保持；原完整编辑器证据仍保留。完整产品root/导航弹窗与真正窗口切换hidden行为仍需后续实际页面验证，本批方法调用不当P8/373或完整产品验收。

下一步继续需求属性/生命周期的真实操作、详情业务区与父级绑定、产品入口和生产构建。真实计数方案/效果样本及付费预算仍开放，资源/接口/算法已批准部分无需重复确认。
