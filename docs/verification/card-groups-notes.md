# 卡片消息集合与实际对话读取接线

接续e01e3a1。重读FE DT-AI/5.5的真实消息、结构损坏降级、卡片状态及BND-CARDS父级归属；完整单组C06/I36/SHR-CARDS依据沿用上一单元已读正文。当前单元新增guide/card-groups.ts/card-message.tsx，既有AiReadPanel/MessageTimeline通过真实structured回调在原I35 article内渲染控件，不插入或重新排序任何消息，也不把卡片草稿当正式回答。

RequirementCardGroups订阅实际AI父级与RequirementMessages的成功窗口，按完整实际消息ID保留独立InteractionCards owner，来源Run由真正I16读取。详情变化同步生命周期/占用；实际卡片状态/正式回答变化分别采用。每组原输入、原键请求、UNKNOWN与CONFIRMED都不因其他组到来而更换或退休；损坏历史结构不显示旧控件，保留原可读正文。关联回答按reply_to_message_id与原组绑定，重复关系/外来Run/来源读取失败显示错误并阻止该组操作，实际源重读成功恢复原owner和输入。

真实隐藏/窄屏/历史等由setAvailable停所有组和本集合源GET，展开只从实际窗口恢复；旧epoch与被更新窗口取代的源读取不能采用。组件读取busy仅禁用控件，不改变组自身availability epoch，避免I36确认后自己的资源协调被误当隐藏。退休解除全部订阅并退休真实组，不发取消或新提交。已经接受的正式回答不会被事务前开始、事务后才到达的旧AVAILABLE窗口覆盖，身份相异正式回答拒绝采用；finish仍要求实际I35的ANSWERED及同一正式回复。

新增8个端口检查：[最终228前端及TS](frontend-2026-10-06T05-42-41-667Z.json)通过，187输入hash不变，另4项development检查通过。覆盖不同组隔离、EXPIRED精准清理、UNKNOWN跨ANSWERED/新组保原动作、来源失败重试、损坏历史禁旧控件、晚读隐藏退休、新窗口替代与接受后旧窗口不回退。初版7项检查曾持续占用事件循环，首次整体与单例测试无正常完成；已明确停止本次创建的两个Node测试进程树。原因是发布时冻结了局部工作slots后又原地更新，异常后finally无界自动重试。改成发布副本、只在真实隐藏代次变化时补调度；失败保错误并由明确重试处理，不掩盖或自动循环。修正后7项及补充第8项全部通过，没有遗留测试进程。

[最终实际编译对话浏览器/API/SQLite](cards-browser-2026-10-06T05-42-42-101Z.json)通过，413输入hash稳定、preview健康、CLI关闭、正式API服务退出0。复用明确私有持久卡片前置夹具，没有新增模型/Provider假证据。全部上一单元真实四卡控件校验/焦点/存储失败/真正reload恢复、两组I36丢202原键重放、确认后消息读取失败仅读恢复、INITIALIZE新Run4/WAITING同Run5与不同键409安全response5均在真实MessageTimeline接线后再次通过。初始化prepare1/send2/receive1/read8/refresh2，等待prepare1/send2/receive1/read6/refresh1，正式后续FAILED不撤销回答。

本单元过期用正式消息工具栏“刷新消息”读取I35，由集合自动同步；没有调用单组刷新接口来代替父级联动。需求2持有卡片7 ANSWERED及卡片10 EXPIRED，均无源错误/loading，两个owner各自RESOLVED；实际DOM消息ID按[2,6,7,8,9,10,11]顺序与实际I35逐字对应。普通I15替代通过明确诊断调用真实C02事务，此诊断调用未走普通发送控件的Run接收回调；因此不能把其最后一次旧WAITING运行展示/完整普通发送联动称为本单元的整个AI父级验收。卡片过期的证明是实际I35与自动集合采用，零该组I36/正式答案，read3/refresh0（该计数指单组确认回调，不包含独立消息工具栏GET）。后续完整对话父级仍须接既有正式composer.receive及run-actions，验证普通文字与卡片并发竞争。

最终2需求/2CURRENT/1Revision/0评论/6Run/0LLMUse，全文身份/版本/区块元数据不变，无Provider出站/付费。局部实际对话截图已查看；4张卡片异步加载引起的消息高度变化与滚动锚点、整页正式视觉/完整详情根入口仍需后续浏览器验收，不能沿用旧纯文本滚动证据覆盖这些新范围。[中间227前端](frontend-2026-10-06T05-40-37-352Z.json)及[中间集合浏览器](cards-browser-2026-10-06T05-40-37-804Z.json)均保留。

当前卡片单组与集合/真实对话专项均已保存验证；下一单元先处理真实异步卡片高度与消息阅读锚点，再读FE BND-SUGGESTIONS/DT-OP12–16及BE SHR-PATCH、C01–03、I20–23，实现建议读取/单项决策/纵向原新内容/完整批次采用与恢复。普通发送/运行命令/卡片的统一对话父级、产品根入口/正式构建、373/P8与Provider预算兼容/真实效果仍开放。后端730仍为历史证据，Windows间歇运行时退出未由本单元宣告根治。
