# 详情正文与历史会话父级专项（2026-10-06）

依据FE BND-DETAIL进入/恢复、5.5人工编辑/历史隔离/导航/窄屏/失败分支、DT-OP15/16/23–26、BND-EDITOR和批准D-004/D-009；本轮完整重读现有detail-read/manual-session/revisions/read/components/manual-controls及对应实现，重用真实控制器，不另造版本或回执。

requirements/document-owner.ts/document-controls.tsx统一管理唯一主文档区域中的实际CURRENT、人工会话和真正Revision。各异步编辑器有独立所属host，创建失败/退休不清除父级其他DOM；串行采用、忙状态、关闭检查。开始编辑后读取独立草稿及真实本地恢复对象，仍须用户选择后端或本地。Header采用真实详情，成功结束再重读CURRENT。manual-session增加内部HISTORY阻断原因，导航setVisible关闭已停放快照的浮层/定位，均不改公开字段。

进入历史先冻结并保存最新完整草稿，保留同一编辑器、账本和缓存；草稿不能确认保存时保留且给警告，历史仍只读。读取/展示失败保留实际已展示历史与停放对象。退出必须完整实际详情读取，保存基线与实际活动关系复核后才关闭历史；失败保留历史。外部草稿v3与本页v2竞争时READ_CONFLICT锁定，不采用较新GET覆盖本地；展示两份完整Markdown对照，唯一额外结束入口是显式确认放弃整个人工草稿，使用现有I13取消/原未知动作恢复，确认后再次完整读取才退出。确认取消本身不发请求。该控件没有自动合并或恢复历史正文。

最终证据：

- [140前端/TypeScript/依赖](frontend-2026-10-05T19-04-26-423Z.json)，146输入hash不变。
- [真实编译页面/浏览器/API/SQLite](document-browser-2026-10-05T19-04-16-506Z.json)，371输入hash不变，Vite测试页面build退出0、preview存活/代理API200、正常关闭。最终2需求/2文档/1初始化版本/0评论/2缺配置Run/LLMUse0。
- 真实Header I09创建草稿3，显式继续后端，原生输入历史停放保留😀，进入历史I11保存至v2，同一session/editor冻结隐藏，实际BASELINE Revision1只读；CURRENT仍v1。
- 第一次退出在实际I37成功后故意丢失本地读结果，仍保历史/草稿；下一次完整读恢复同一editor/session且原生内容仍在，已保存/可输入。实际I12完成后读取CURRENT2/v2。
- 第二实际草稿4本地v2含冲突保留本地😀；另一真正RequirementEditor/账本/I11保存后端v3含另一页后端更新😀。退出拒绝，两份完整内容独立且旧编辑器只读；取消确认保编辑状态，随后显式确认I13取消/重新完整读恢复CURRENT2/v2，两种冲突输入均未进正式正文。
- 全过程10次完整详情读取；退休只移除自有host、父级兄弟DOM保留；已排队但尚未执行的adopt遇退休跳过且不创建编辑器或读HTTP。验证是queued分支，不冒充所有已发送请求迟到分支。

失败/中间报告保留：初期140前端18:52:56/18:55:47（文件UTC时间原样）及[初次组合](document-browser-2026-10-05T18-56-01-244Z.json)通过，尚无冲突/退休专项。[扩展18:58:50](document-browser-2026-10-05T18-58-50-576Z.json)初次CLI snapshot无输出退出127，尚未创建需求，不能计业务通过，原因未证明；诊断snapshot后来能执行。[扩展18:59:44](document-browser-2026-10-05T18-59-44-481Z.json)在真实草稿创建后Windows Vite dev进程0xC0000409退出，恢复GET真实连接失败、控件保持ERROR/只读/可重读，非产品业务成功。测试专项改为独立目录编译api.html及preview，仍同一正式API/SQLite与产品源代码、原生交互断言未降低；[完整冲突初次通过](document-browser-2026-10-05T19-02-34-043Z.json)与最终报告通过。只证明编译预览替代路径稳定，不声称已根治开发进程退出；19:04最终报告覆盖退休补充。脚本一处多余括号在运行前SyntaxError，修复后node --check通过，未启动该次服务。

已查看output/playwright/document-owner-history.png/current.png/conflict.png：1280×720诊断中历史标识、大纲和两份对照可读；仅当前视口，模板/末尾marker不全部出现在截图，不当完整产品视觉验收。逻辑正文和身份由真实API及浏览器全量断言验证。

范围仍有限：已验证正文/Header/人工/历史父级，不是完整Detail页面或根路由。实际DetailFrame窄屏、真正站内导航/beforeunload、评论标记及选区、AI消息/卡片/建议、版本保存按钮与全页签、完整生产根构建、真实Windows IME/全部视觉/373及P8仍待。外部占用结束或换草稿等冲突能保内容/展示最新正文，放弃按钮仅实际同ID MANUAL草稿开放；更广泛人工处理和离开保护接入尚待。Provider兼容/效果/预算开放，未调用模型。后端未改，730历史证据保持，所有本轮服务正常关闭。
