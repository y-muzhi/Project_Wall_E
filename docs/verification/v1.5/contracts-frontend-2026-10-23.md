# V1.5公共读取与完整前端专项

2026-10-23，未提交工作树；独立于此前浏览器记录，不把新分析展示称为已浏览器验收。未访问用户数据、真实API或用户服务。

## 实现及修复

- RunView.final_result新增真实已保存Analysis或null，包含完整发现／覆盖／未决；RUN_RESULT来源不再用message摘要替代。六操作标签来自实际operation；model_calls列表与详情同步。
- 批次完成明确原8字段正文投影，新增实际HTTP字段集合断言。卡片related_spec_context严格包含document_id、content_version及block_id，修复非空关联正文无法解码的问题，并显示实际身份。
- 需求属性PATCH在准备请求前拒绝未知changes，避免分配原key后才在回执检查发现非法字段。
- 页面销毁前排队的状态写不再发送；已发送命令保留原请求，不用读取AbortController中断标题UNKNOWN的写重放。
- composer恢复在父读取返回后先核实视图代次和需求归属，再读取消息；已隐藏的旧恢复不发后续GET或重放。实际接受回执按严格RunReceipt核实后才确认。

## 实际结果

- `pytest -q`运行model_calls、execution、recovery、worker_recovery、batches，28 passed，141.89秒。完整Analysis只读HTTP／SourceRef及模型结果已保存对象核对均包含其中。
- `pytest -q backend/tests/guide/test_v15_scenarios.py`，2 passed，25.73秒。独立电影及实验耗材用例，经实际HTTP／SQLite覆盖讨论→建议暂缓PROGRAM无调用→明确生成→BLOCK修订→在途CLOSED→旧新两Revision比较→RUN_RESULT作为检查来源；每例5次显式离线Counter／Gateway轮次，无隐式调用、范围外变化或多余CONTENT。这是程序行为验证，不是模型语义效果EV。
- C09新增未解析响应恢复时的写入失败：最初注入旧审计方法未触达新建路径，专项真实失败已保留；改在实际RevisionRepository.insert_content注入，最终6 passed，22.53秒。解析／CURRENT／Revision／审计全部回滚，原始返回保留，恢复再做一次程序提交，无新LLMUse。
- 旧前端专项初次扩大检查357项／233通过／124失败，包含过时INITIALIZE／WAITING／同轮继续及缺新对象身份的夹具。已按正式设计逐文件更新，保留原输入／并发／未知回执／迟到读取场景，将已删除语义替换为五态元数据、新轮继续和真实固定目标；没有放松产品契约或跳过失败来报通过。
- 完整前端`node --test --test-reporter=tap tests/*.test.mjs`最终355 tests／355 pass／0 fail／0 skip，3925.67毫秒。完整`tsc --noEmit`通过；TemporaryDirectory生产构建1253模块／606毫秒通过，仅既有大chunk提醒；临时目录已清理，未覆盖frontend/dist。此后如果再改产品代码，应运行受影响检查并另记最终结果。
- `tools/cleanup-test-artifacts.py --dry-run`：JSON=0、screenshots=0；没有留原始输出。后端22文件全联合另行执行中，已观察失败，当前不得记整体验证通过。

## 尚未覆盖

当前扩大联合发现的后端失败须定位并修复；资源实际LIVE_VERIFIED凭证接入／异常SUSPENDED和供应方原始total展示仍需实现核对。真实Tokenization／Chat、EV四类效果、全部浏览器焦点及长表格组合均未执行；不沿用历史付费授权。
