# 修改建议独立页签检查

2026-10-27，M15-SUGGEST-02。基于HEAD48fab5bd67c01e2542cecdb9336ea2a27c0513da的工作区增量，保留之前未提交修改。本任务仅前端页面、原owner可见性／读取、相关离线／类型／临时生产构建和隔离页面，真实模型／计数0，用户库0写入，Git0写入，用户服务0启停。

## 实现与正式依据

已读正式FE详情、BND-SUGGESTIONS、INF-BROWSER及原Frame／Layout／Conversation／批次owner／detail-owner，未重审全部模型资源。新增SUGGESTIONS顶部页签，顺序AI对话／进展／修改建议／评论／文档记录；原AI内部二级切换移除。建议面板整体复用独立槽，原消息和建议组件均保持挂载。Conversation区分AI和建议的可见性／权限，AI刷新不再额外调用批次owner刷新；隐藏建议禁止新决定并保留原请求和草稿。详情既有活动／占用读取仍保留，本轮不声称初次AI页面没有任何batch GET。

10文件按路径UTF8＋NUL＋原字节＋NUL排序聚合SHA256=3f290ea93de793b296a448b9f3e055f3c70fe7f023617b0cb19f0a05a61285bd：requirements/detail-layout、detail-frame、detail、detail-owner；guide/conversation、conversation-owner；shared/styles；tests/detail-layout、conversation-owner、browser/detail-frame-probe。正式FE新SHA256=f23f832f1adbd9814212c68e11c4a21776f54116ec73666b41a0ccab2d2d8857，BE保持fc34481af473ea40617cd859329f07aa03147c19d983f3f700c1b6a9ea02359d，均1.0／EFFECTIVE。无后端／资源／AI协议变化。

## 离线与构建

- node --test tests/detail-layout.test.mjs tests/conversation-owner.test.mjs tests/suggestion-batch.test.mjs：34 passed，404.5162ms。覆盖新偏好／原合法值、独立可见不读取消息和Run、原批次及编辑跨页签保留、隐藏／历史禁止新决定、批次到达不强制切换，原UNKNOWN精确恢复及批量保护继续通过。
- npm.cmd test：405 passed，5236.4575ms；npm.cmd run typecheck退出0。没有新增后端专项，因为HTTP、事务及模型行为未修改。首个检查包装器在测试退出0后因控制台GBK无法打印勾号而退出1，切UTF8输出后保存了上述34项结果；不是产品测试失败。
- tools/serve-v15-offline.py --serve在独占TemporaryDirectory内执行node_modules/vite/bin/vite.js build --outDir <独占根>/frontend，退出0后才启动真实应用，未覆盖frontend/dist。仅原既有工具Starlette弃用提示；构建输出未留原始日志。

## 实际隔离浏览器

使用Playwright技能CLI、真实前端／HTTP／SQLite／Worker及私有Counter／Gateway。独占站点PID52764／PTY67722／52368，根walle-v15-browser-s03dqs4v，命名浏览器walle-suggestion-tab。用正常隔离API建立文档和15项真实待处理建议，仅2批私有计数／2次私有Gateway，外部供应方0；另建零文档／零批次需求不调用模型。

- 顶部实际5个页签按指定顺序，AI DOM内suggestion-panel数量0、conversation-view-switch数量0；切到修改建议真实15项可见，AI隐藏。没有将列表继续放在AI内部。
- 填写对话草稿“切换后保留的对话草稿”，第一项打开编辑并填“建议编辑草稿保留检查”；切回AI再返回，两者原值均保留。建议列表scrollTop=260往返后仍260，原编辑控件保持；未保存编辑时批量保持禁用。
- 修改建议页签ArrowRight切到评论并聚焦detail-tab-COMMENTS，ArrowLeft回SUGGESTIONS并聚焦；1100×800面板420px，页签宽338px／内容338px，页面无横溢、可见alerts空。1600×1000布局亦无横溢，1份临时截图已实际查看，内容及顶部入口可辨。
- 存储right_tab=SUGGESTIONS；进入新零批次需求，正确保留页签并显示“暂无修改建议”，没有显示上一个需求的批次。
- 全部交互后隔离15项仍PENDING，C04记录0、模型调用仍2；没有在浏览器代提交接受、拒绝或最终应用。console消息0／错误0／警告0。工具find新版本只接受文本参数，初次多传text报用法错，及一次Windows嵌套引号导致eval参数错，修正调用后继续；没有产品错误或重复业务提交。

## 清理、用户现场及边界

命名浏览器已close；PTY67722发送stop后退出0，Counter2／Gateway2，OWNED_TEMPORARY_SERVER_STOPPED_AND_OUTPUT_CLEANED。临时截图／快照／配置／SQLite均随独占根清理，不留JSON、媒体或原始日志。

用户8000／47020、5173／12440原进程保持，本轮不重启后端。4项只读GET：5173需求2页面、detail-frame模块、conversation模块、共享样式均200；实际模块含SUGGESTIONS／ConversationSuggestions、旧二级切换已无。Vite加载新源码，用户可刷新http://127.0.0.1:5173/requirements；8000静态dist未重新部署。未请求用户业务POST／PUT，未读凭证或触发真实模型／计数。

未覆盖：本轮未重新执行批量接受实际提交链（上专项有独立证据），未重测表格编辑全链、其他浏览器／高倍缩放、完整BFCache及跨标签组合；原运行／建议UNKNOWN与共享互斥由相关回归覆盖。没有新增“自动恢复最近已完成批次列表”，历史批次仍从原运行选择进入；无绑定批次显示空态。整版人工语义审阅仍独立。

静态收尾：26份变动Markdown共397个本地文件链接有效，git diff --check退出0；新正式FE／原BE摘要复核一致。独占根walle-v15-browser-s03dqs4v不存在，cleanup-test-artifacts.py --dry-run为JSON0／截图0。所有实现及规定检查完成，无待重启／待合入步骤。
