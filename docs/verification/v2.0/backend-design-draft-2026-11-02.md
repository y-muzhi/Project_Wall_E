# V2.0后端设计首稿静态核对

日期：2026-11-02（Asia/Hong_Kong）。Git基线：master，8c5df4c6683e10c265e2f719a4fdc09ba4210ea0。

## 范围及产物

用户在阅读及架构分析后要求继续推进；本轮编制[后端设计DRAFT](../../design/v2.0/WALL-E.后端设计文档_V_2.0.md)，先保存[独立架构迭代](../../iterations/pending/v2.0/WALL-E.代码任务架构细化迭代_V_2.0.md)，同步[设计断点](../../project/v2.0/设计进度_V_2.0.md)及必要导航。未改V1.5正式设计或V2.0原汇总，未自动合并／归档pending。

## 环境及实际命令

Windows PowerShell、Python、Git。Get-Content／rg读取文档及相关源码，git status --short核对工作区；Python内存脚本检查Markdown本地链接、结构、定义引用、空白及保护摘要；git diff --check核对已跟踪差异。所有文档整文件保存均经同目录临时文件、flush／fsync、关闭、复核原字节后os.replace，清理本轮临时文件。

外部资料只读使用[OpenCode Server](https://opencode.ai/docs/server/)、[Config](https://opencode.ai/docs/config/)、[Permissions](https://opencode.ai/docs/permissions/)、[Git update-ref](https://git-scm.com/docs/git-update-ref)及[worktree](https://git-scm.com/docs/git-worktree)。网页说明只作设计依据，不是锁定版本或兼容验证。

## 实际结果

- 9份本轮Markdown的40个本地链接均存在；10个外部链接用于资料引用，未作为协议验证。
- 后端第1—8章顺序完整，44个稳定对象／应用／机制／公共规则引用均可定位定义；34项TC20验收场景编号唯一。未发现未替换模板占位、表格列数不一致、末尾空白或未闭合围栏。
- 手工复核状态—动作、逐操作完成条件／未知恢复、候选与检查／计划绑定、模型预留及终止交付竞态。复核中补齐ExecutionRecord观察读取、检查后的跨层返工和LLMUse代码专属投影。
- 读取现行llm_uses Schema确认原guide_run_id非null及CHECK(call_no=1 AND attempt_no=1)。草稿明确双归属与按归属区分约束、NOT_APPLICABLE输出校验、审计／查询及显式升级；没有执行Schema修改或迁移。
- git diff --check通过；新增及忽略目录中的Markdown另经内存检查，不把Git忽略文件漏查成已通过。
- 初始12份保护文档中的10份规则／模板／正式FE／BE／V2.0原汇总／建议／批次／原来源／路线图摘要保持；V1.5实现进度及需求映射在工作期间被另一轮M15-CURRENT-DOC-01更新。本轮读取其当前断点确认独立任务范围，没有覆盖或回退。
- backend/app、backend/resources、frontend/src的637份文件集合，初始SHA256为e26ce97be64c73b29aaaf9f99c352a05d30cfa33b7f56c23da675920fd5433dd，最终静态检查时为bf80474b60791360c47061df715003e1563b5f28eca4e0d9f9290eb423b2dc59，二者不同。git现场新增6份frontend/src及2份既有前端测试改动，与上述并行任务记录一致；不能声称全项目源码摘要未变。本轮工具写入范围仅9份Markdown，没有触碰源码／测试／资源／业务库。
- 所有本轮同目录临时文件已清理，无本轮自有服务或测试进程。既有V2.0设计、project及pending目录仍受.git/info/exclude原9—11行排除；未更改排除规则或把本地资料加入Git。
- 后端首稿SHA256：f899afc7ef2fc2ac8d6abe62828a586d3b11b6236ae79788d3b70e490da7a2fc。设计断点已保存已读／未读、DRAFT选择、未验证项和下一步；没有提前创建实施完成记录。

首次保护检查没有“全通过”：它发现2份管理文档及源码集合变化；后续只读核对确认并行任务并记录实际差异。没有靠重新选基线掩盖该变化，也没有把该检查差异判成产品缺陷。命令输出首次包含中文编码显示问题，重读时改用ASCII JSON传递摘要；无文件写入受影响。最终摘要更新脚本曾因占位变量漏替换出现NameError，写入前退出；更正后保存并重新检查。


## 未执行及限制

未执行产品测试、类型／格式工具或构建、浏览器、OpenCode安装／协议试验、模拟模型服务、真实模型／计数调用、业务数据库读取写入、Git交付、提交推送或服务启停。没有新增测试JSON、截图、录像或原始日志。正常业务审计和数据库未作清理。

后端附录A的版本、协议、Windows、模型、内容、Git、检查资源及升级仍待验证，前端详细规格未创建。静态检查只证明文档结构／引用及文件保护，不证明架构实现正确或产品可用。
