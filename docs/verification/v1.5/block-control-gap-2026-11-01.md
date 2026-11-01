# 无折叠区块操作间距检查

日期：2026-11-01。M15-BLOCK-GAP-05。代码状态：HEAD33a6736及原未提交修改，本轮仅修改frontend/src/documents/navigation.ts和既有tests/navigation.test.mjs；其他源码／v2.0资料保留。规则先记入[独立迭代](../../archive/iterations/v1.5/WALL-E.无折叠区块操作间距修正_V_1.5.md)，正式FE／BE不改。本记录不表示全产品验收。

## 实现与原因

原公共方法始终预留六点＋箭头的两槽；没有箭头的列表／段落也留下32px空位。公共方法增加hasFoldControl输入，controls／measure从真实foldable_headings传入；无箭头时六点使用靠近区块的一槽，含箭头布局保持。原首行中心、视口约束、24×28尺寸、悬停菜单和正文padding均不改。所有保存为同目录临时文件fsync／关闭／并发复核后原子替换。

## 实际检查

- Windows、项目锁定Node依赖、strict／未使用规则保持。frontend下`node --require ../tools/quality_node.cjs --test --test-reporter=spec tests/navigation.test.mjs tests/section-navigation.test.mjs tests/section-folding.test.mjs`：10通过、0失败（1644.2003ms）。在原几何专项增加无箭头间距、padding及视口左右界断言；已有标题、折叠范围／状态等检查通过，不另造样式镜像测试。
- `npm run typecheck`、`npm run format:check`均退出0。未执行生产构建或全量业务测试；本批变化不涉及资源发布／后端契约。
- 当前5173的/src/documents/navigation.ts源映射sourcesContent与磁盘完整源码一致，关键导出及hasFoldControl真实存在；不以HTTP200替代服务加载证据。
- 独立Chrome只读访问/requirements/2，API写入在浏览器层阻断。改前1280px实页列表距六点右端48px（理论52px受左视口约束），改后20px。1280×900及1920×1080关闭助手、1920×1080展开助手，共3种布局中列表／段落均20px，按钮24×28、首行中心偏差0px；按钮出现前后区块x／y／宽／高变化均0px。含箭头标题按钮间仍8px、首行中心0px；箭头距区块实际16px，沿用原20px目标受视口夹限后的结果，本轮未扩大正文padding或改动标题布局。
- 原六点悬停打开菜单、离开关闭，以及标题点击收起再展开均通过。截图已查看：列表按钮靠近蓝色区块且不覆盖内容；查看后删除。API写请求0，Console错误／警告0。

## 清理与未覆盖

两次自有浏览器会话均close退出0；TemporaryDirectory中的快照／日志自动清理，唯一临时预览PNG及目录已删除，不留JSON、截图、录像或原始日志。未启停用户8000／5173、未枚举PID、未编辑正文／评论、未结束／取消人工编辑、未触发真实模型／计数、未提交推送。正常启动方式仍tools/ai-service.py --start --credential-file .env.local及frontend下npm run dev，本轮未执行。未进入人工编辑／历史模式或其他浏览器，相关原业务行为未因本轮只读几何检查重新宣称验收。
