# 新建需求移除初始想法检查

日期：2026-11-01；M15-CREATE-IDEA-01。HEAD fed094c9f4d87f39f03f4efef142ee14b062f493，检查当前未提交工作区，保留上一轮文档级隔离变更。规则见[独立迭代](../../archive/iterations/v1.5/WALL-E.新建需求移除初始想法_V_1.5.md)，正式设计未合并。

## 实际改动

create.ts／create_drawer.tsx移除idea字段、校验、提示、错误映射和焦点项；标题＋类型构成正常创建正文，说明改为“创建后可添加文档”。api/walle.ts允许仅两字段提交；后端requirements/contracts.py与http_models.py允许省略initial_idea，按空正文处理，明确提供的值仍校验Unicode／10000码点，null仍拒绝。

保留initial_message_id实际依赖及既有数据；空正文根创建记录不进入文档助手默认历史／上下文，不补写标题或占位文字。原创建幂等、UNKNOWN原请求、草稿保留与取消继续复用。无Schema变更／迁移／清库、资源变更或真实模型／计数调用；源码全部同目录临时文件flush／fsync、关闭、并发核对后os.replace。

## 检查

Windows／PowerShell，项目.venv Python3.13.5、锁定Ruff与现有Node依赖。离线专项使用quality_node／quality_python守卫，拒绝真实外网、正常data及凭据，SQLite限定自有临时根，原始输出仅在内存。

| 范围 | 命令／实际方式 | 结果 |
| --- | --- | --- |
| 前端受影响专项 | node --require tools/quality_node.cjs --test --test-isolation=none --test-reporter=tap requirements.test.mjs、api-bindings.test.mjs、v15-foundation.test.mjs（实际使用绝对路径与frontend工作目录） | 20 passed／0 failed；覆盖两字段Wire、码点、冻结原请求／key、UNKNOWN、失败保留与dispose |
| 后端创建与HTTP | python -B tools/quality_python.py backend/tests/requirements/test_v15_foundation.py -q -p no:cacheprovider --tb=short --basetemp 自有短临时根/pytest | 9 passed／1个TestClient依赖弃用警告；包含省略正文201、空正文保存、与显式空正文同key重放、null／过长422、零模型调用 |
| 类型／格式 | tools/check-v15-offline.py --only format --only python-format --only typecheck --only build --timeout 120 | 前端格式、后端Ruff格式、strict类型均通过；该次临时构建因沙箱临时目录权限失败，原失败记录保留 |
| 临时构建复查 | 同quality_gate.commands的build，经run_stage，普通短系统临时目录 | 退出0，临时目录finally清理成功 |
| 正常静态资源构建 | npm.cmd --prefix frontend run build | strict类型与Vite构建退出0，1269模块，仅既有大chunk提示 |
| 运行模块 | 5173 GET requirements/create.ts、create_drawer.tsx、api/walle.ts | 模块非空、有预期导出，source map内容与磁盘一致 |
| 实际浏览器 | Playwright技能，现有5173工作台／新建抽屉 | 仅title／type两个data-field，textarea0；640×800与1440×900按钮可见且不越界；空提交只有标题／类型错误；Esc取消，未提交有效创建；Console错误0／警告0 |

## 服务、数据与清理

两字段表单须加载后端可选字段修改，检查完毕后核对8000实际进程归属及RUNNING0／人工占用0，再停止旧PID48312、正常build后使用原安全助手启动新后端。最终8000 PID14496，5173原PID14996保持（仅表示检查当时）。正常启动仍tools/ai-service.py --start --credential-file .env.local，前端npm run dev；后续启停需重新核对，不以旧PID判断。

新后端实际无initial_idea的超长标题请求返回422，错误仅title，证明可选契约已加载；在持久化前拒绝，没有创建业务记录。重载前后需求／文档／消息／运行／调用／评论／建议数量一致，分别为1／1／2／0／0／0／0，没有清库或代改现有正文。浏览器只空表单校验／取消，未做正常库成功创建。

首次前端专项19／20通过，修改测试的快照输入时误写getter-only title，后改为修改可写requirement_type，20项复查通过；没有修改生产实现绕过失败。首次门禁临时构建失败及清理权限见[原记录](quality-gate-2026-11-01-222706-566865.md)，普通短临时根复查成功，失败路径事后核对不存在。最初误直接执行quality_gate模块没有运行main，未计为通过，后使用check-v15-offline.py入口。

浏览器首次误点导航后尝试打开新建，被导航弹层拦截；关闭导航后按实际新建按钮核对通过，不将工具超时记作产品故障。自有浏览器close0，output/playwright/create-without-idea与本轮日志／快照已清理；cleanup-test-artifacts.py --dry-run为JSON0／screenshots0。

未重跑前端447或全部后端，上一轮数量不当作本轮证据；没有新增低影响界面镜像测试。真实供应方、多浏览器、真实IME及处理中／UNKNOWN视觉没有新增证据，原逻辑由本轮20项创建专项覆盖。无未完成实现分支，不提交推送，不自动合并正式设计。

最终静态收尾：14份当前变更Markdown的365个本地链接目标、唯一当前断点及git diff --check（将CR视为原Schema行尾）通过；正式FE／BE摘要保持原值。源码／测试／资源摘要d3b767b27bfeed6e384099fdc7b3efa634b948bf2fd68921c667ec8835f4c4aa与本轮门禁时一致。8000正常静态入口200，自有失败构建临时路径确认不存在。
