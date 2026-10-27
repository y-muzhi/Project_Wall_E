# 文档记录入口收纳检查

2026-10-27，M15-RECORD-01。基于HEAD48fab5bd67c01e2542cecdb9336ea2a27c0513da工作区增量，保留此前未提交修改。只改前端／正式FE和实施记录，不改后端、资源、用户库、Git或用户服务，不调用真实模型／计数。

## 实现与依据

已读根AGENTS、进度／映射、正式FE详情／记录／菜单及偏好，实际RequirementHeader原tools插槽、DetailFrame／Layout／DocumentRecords；未重审全部AI资源。更多操作增加“文档记录”，辅助面板常驻只保留AI／进展／修改建议／评论。原REVISIONS和DocumentRecords整体复用；记录显示同一标题行“返回／文档记录”，内部版本／运行页签保持。返回此前主视图，冷恢复REVISIONS无前视图默认返回AI；菜单关闭焦点进入返回按钮，返回后焦点回主页签。旧REVISIONS偏好合法，原版本说明、筛选、对话及建议组件不卸载。

改5文件：requirements/detail-layout.ts、detail-frame.tsx、detail.tsx、shared/styles.css、tests/detail-layout.test.mjs；路径UTF8＋NUL＋原字节＋NUL排序聚合c624e9867a0e2dce8c10aa0f1f826fed2eb763f8b267e41ae52b60bfd2ed4d09。正式FE SHA256=e1d4fb40cf93293513062d8be2a1d453ea5ad693e7d06ac126cb66e77d477a1c，BE保持fc34481af473ea40617cd859329f07aa03147c19d983f3f700c1b6a9ea02359d，仍1.0／EFFECTIVE。

## 相关检查

- npm.cmd run typecheck退出0。
- node --test tests/detail-layout.test.mjs：10 passed／345.6673ms，新增返回四种主视图、重复打开、宽度不变、旧偏好冷恢复、受限视口不切业务视图。
- npm.cmd test：406 passed／2508.2718ms。无新后端检查，因为服务端行为未变。
- tools/serve-v15-offline.py --serve自动在TemporaryDirectory内Vite生产构建，退出0后启动隔离真实应用；未覆盖frontend/dist。仅工具既有Starlette弃用提示。

## 隔离页面及清理

沿Playwright技能CLI，独占PID51264／PTY71456／53226，根walle-v15-browser-8tromyjo，浏览器walle-record-more。使用真实HTTP建立独立需求及空白文档V1；初次夹具误传小写brief被422严格拒绝，核对原契约后改为REQUIREMENT_BRIEF创建201，没有修改契约。模型／计数私有与真实均0。

实际验证：主tablist四入口、detail-tab-REVISIONS数量0，更多菜单中“文档记录”真实可见；点击后菜单关闭、recordsVisible=true，焦点为“返回辅助面板”，无页面横溢。旧REVISIONS偏好reload仍能进入记录，真实V1显示；冷返回AI，焦点detail-tab-AI。填对话草稿“文档记录往返保留输入”，从评论进入记录、切运行记录，原分类可用；返回后仍评论、焦点detail-tab-COMMENTS，草稿精确保留、可见alerts空。无代提交版本说明、历史恢复或AI，console0／错误0／警告0。

浏览器close，PTY71456 stop退出0，OFFLINE_COUNTS count_batches=0 chat=0，自动清理完成；独占库、配置、快照无保留，不留媒体／JSON／原始日志。用户8000／47020／PTY84129、5173／12440原进程保持；四个不同只读GET（需求2、Frame、detail、layout模块）均200，实际新模块具菜单入口及记录返回。第一次检查detail模块按未编译单引号原文匹配失败，Vite转换引号后重核“文档记录”及REVISIONS两片段通过，并非服务失败。用户可刷新http://127.0.0.1:5173/requirements使用；无后端加载步骤，8000静态dist未重新部署。

未覆盖：未重新跑记录分页／请求详情／历史恢复写入或其他浏览器／缩放全组合；原记录组件未修改，相关既有回归继续通过。不把布局可用当作整版人工语义或真实供应方新验收。

静态收尾：29份变动Markdown／416个本地文件链接均有效，git diff --check退出0，正式FE／BE摘要复核一致。独占临时根不存在，cleanup-test-artifacts.py --dry-run为JSON0／截图0。没有剩余实现／合入／服务加载步骤；未提交推送。
