# V1.5 v13条件批次实际结果

2026-10-24，Asia/Hong_Kong，固定输入a6b92ffe…，源码67a8f51d…，v13 release eeb7925e…；详细授权见v13-final-batch-authorization-2026-10-24.md。

阶段1：1批纯计数，预计输入158716>131072，正常精确摘要通过，0Chat，阶段2条件成立。

阶段2：1计数＋1Chat，技术usage／framing／LIVE通过，parse成功但业务validation失败：输出缺三个必需null根字段，首轮结构门未通过。实际输入8177／输出1872／总10049／缓存0／gap3，零重试。

阶段3：26EV全部未发送；本批结束，总计2批Tokenization／1Chat，总Chat Token10049。未用次数不续用，不换输入／版本重试。不动用户库／服务，无Git写操作或模型裁判。

原正常证据7个SQLite／计数审计／准入JSON聚合SHA256=3bfac2b0e14befd5be3a1d9a69517281a239111f5c476ce7a2fccd15db7a7a80（项目相对POSIX路径排序，路径UTF-8＋文件SHA二进制）。保留原结果；离线诊断副本不回写原库。具体记录live-count-gate-v13-final-once及live-observation-v13-final-once-2026-10-24.md。
