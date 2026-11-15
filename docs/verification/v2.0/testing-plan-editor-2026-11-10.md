# V2.0 Testing 结构化计划草稿与测试包入口

2026-11-10，工作树 master 28a7c9e 上未提交的 V2.0 实施。使用仓库 Playwright CLI 验证入口及本轮专有 Chrome Job、随机本地端口、隔离前端构建和协议夹具。

执行 `tools/verify-v20-command-recovery.py --probe testing-plan-editor`（使用本机已缓存的 Playwright CLI 入口）。结果 `V20_TESTING_PLAN_EDITOR_PASSED`，360／1280／1920 CSS 像素三档，草稿写请求共三次，分别为创建、CAS 拒绝、明确保留输入后成功保存。覆盖从固定版本原文选择引用、添加保留 HTTP 用例及状态断言、刷新后本地输入保留、创建后新建表单收起、冲突后的本地输入和原拒绝回执、同一原保存响应中断后的核对、历史只读、测试包登记断线后原键核对及外部归属拒绝。早期夹具未保存原拒绝或返回早于创建的发布时间，按真实契约修正后复验通过。自有 Job 与临时输出已回收。

TypeScript 与项目 Prettier 通过。后端 API15—17 的 ASGI／SQLite 专项另见[测试包身份](testing-pack-identity-2026-11-10.md)。Chrome 使用协议夹具，CLI／BROWSER 编辑分支、生产独立 Runner、实际测试执行及产品验收另行验证。
