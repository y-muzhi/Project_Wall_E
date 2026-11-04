# 当前文档固定目标与关联文档检查

日期：2026-11-02。代码基线HEAD 8c5df4c6683e10c265e2f719a4fdc09ba4210ea0，master，已有文档脏工作区保留。本轮改动为前端6个src文件、既有反馈专项和文档隔离浏览器夹具；依据[M15-CURRENT-DOC-01](../../iterations/pending/v1.5/WALL-E.当前文档固定目标与关联文档_V_1.5.md)。正式FE／BE、后端、资源及正常数据未由本轮修改，不提交推送。

## 离线与静态

- Node现有安装／frontend锁定依赖；`node --test frontend/tests/v15-composer-feedback.test.mjs frontend/tests/v15-ai-composer.test.mjs frontend/tests/v15-discussion.test.mjs frontend/tests/v15-cards.test.mjs frontend/tests/v15-comment-guide.test.mjs frontend/tests/ai-read-owner.test.mjs`：最终48项通过，覆盖原发送、范围、owner、UNKNOWN／CONFIRMED恢复及反馈。读取生命周期修正后重跑此受影响集合。
- frontend下`npm run typecheck`、`npm run format:check`通过。整文件编辑及格式结果均为内存完整内容→同目录临时文件→fsync／关闭→原文件并发复核→原子替换。`git diff --check`通过；7份本轮文档371条本地链接、唯一当前断点及正式设计摘要保护通过；前端src无“工作目标”“参考文档”“不绑定文档”及旧目标采用按钮残留。
- 正式设计摘要与本迭代开始时相同：FE b294153e11ef764f36f92b7390dc817c6ed079a81734c770ebe6f217601e2920；BE 36d2e28630b5099a30253e5a5881492c8fc50c3cffaf4d9d4a88341bdc24defd。FE原先已有其他任务修改，本轮不覆盖／合并。

## 当前开发服务与浏览器

只读确认现有5173 PID9816、8000 PID20372；没有启停用户服务。通过Python urllib只读取5173的discussion-view、composer-view、cards-view、composer-feedback、composer五个模块，均含有效实际导出；source map的sourcesContent与磁盘源码一致，无空模块。实际导出分别为DiscussionProgress、GuideComposer、InteractionCardsView、composerFeedback、RequirementGuideComposer。

使用Playwright技能及独立current-doc-20261102会话，现有5173的document-assistant-isolation夹具使用实际RequirementDetail／WalleApi／组件，业务请求仅在内存处理：

- 旧null绑定下关联B并保存：document_id和target_document_id均A，scope为DOCUMENT，B只在REVISION来源；保存自然回READY。
- HOLD处理中保存按钮／复选框禁用，title说明正在保存；释放后正常完成。
- UNKNOWN后禁用新保存并说明核实原请求；原body重放，重复回执不会再次增加讨论版本。
- 明确409拒绝保留未发送选择，重新读取后可重新保存；进展GET失败显示原因及重读入口，恢复后可用。
- A／B分别保存关联来源，切换不混接；无文档显示所属缺省且无消息输入；操作设置仍有操作范围，无两处目标选择及旧目标采用入口；取消调整可用。
- 1024×1000与1920×1000实际面板内保存按钮均36px高、无横向越界；左／右坐标分别21／131和1497／1607，所属面板分别21—635及1497—1891。无需新样式补偿。
- 最终隔离流程7次PATCH（含UNKNOWN原请求核实一次），0次POST、0次真实模型／计数。夹具Console错误0，1项原Vue esm feature flags警告及React开发提示。

正常5173工作台及需求1当前文档页面可启动。只读打开进展／关联文档和操作设置、取消设置，确认目标选择移除和新名称；浏览器拦截保护下非GET请求0，正常页面Console错误／警告0。正常库未执行保存／回答／正文写入，不把夹具结果当真实供应方或正常库写入证据。

## 首轮失败与修复

- 首轮格式检查定位discussion-view，按锁定Prettier原子格式化后通过；夹具初次给只读DiscussionState.binding赋值，改为构造新对象，strict检查通过。
- 浏览器首次正常保存停CONFIRMED：实际版本effect清理误中断自身finish读取，已修正active／flow生命周期并完整复查保存／恢复。
- 隔离409夹具初版details为空对象，不符合现有错误契约而被正确视为UNKNOWN；改用契约允许的null后，真实ERROR分支及恢复通过。
- 初次脚本相对工作目录错误、CLI多行参数传递失败、模块探针将InteractionCardsView误称CardGroup，均为工具／探针错误；分别更正目录、使用临时filename及实际导出名后复核。未通过的观测不计入成功证据。

## 未覆盖与清理

未运行全项目测试、生产构建、后端专项或真实供应方；本轮无后端／资源改动，必要受影响前端检查已通过。人工编辑／历史／归档／多浏览器的完整视觉组合、真实IME及长关联名称未新增验证，既有权限门禁保持；不宣称整版验收。本轮浏览器已关闭，无自有服务进程；临时脚本、快照及Console日志按本会话精确清理，仅保留本Markdown。`python tools/cleanup-test-artifacts.py --dry-run`检查为JSON0／screenshots0。
