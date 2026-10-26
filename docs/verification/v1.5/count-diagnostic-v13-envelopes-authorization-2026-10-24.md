# v13一次结构兼容计数诊断授权

2026-10-24（Asia/Hong_Kong）。用户明确答复“授权这一次结构兼容诊断（推荐）”。申领时间=2026-10-24T14:55:58.267906+08:00。

新独占data/v15-count-diagnostic-20261024-v13-envelopes-once，同一固定movie必要全文输入，最多1批Tokenization、0Chat、零重试；不改输入／profile／资源／预算。成功、失败或未知均结束，不重用旧槽，不动用户业务库及服务，不包含后续Chat或EV。私有说明16KiB读取／2048字符上限，脱敏后选择已知错误字段；报告不复制错误正文。

release=eeb7925e52dbecb521ad19a448ba7ae24be4aac63ff8d5b4a0a384ba534c4a68；manifest=6ca926d0aa0954ec2dafc19225a7c65e21bdae1b6db99054667b6957436f8e2d；profile=61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e；backend/app SHA256=4fd73ce286a284bf3f48bfe51cf2e48e3c6a479bb3c5cb174c92bd14cc996c07；tool SHA256=c8ed6c16d6c179cce40c8d2500d91945afd717c2d3168d4401b8fbc8d3983e98。相关原79项、结构补充28项及工具1项分别通过。

原失败请求只读长度核对（不是Token估算／供应方阈值）：{"request_bytes": 1092341, "request_sha256": "8a9f2bc797e5fff066355b54e451d3c6ed733fe1413328334684f15cce3542c4", "text_characters": [10398, 529843, 405, 0, 528518, 89, 240, 483], "text_utf8_bytes": [14404, 530035, 493, 0, 528562, 107, 282, 483]}。凭证从.env.local安全读取，值不记录。

CLI退出码=1；控制台摘要：


本许可已消耗结束，不自动重复发送。

结果对应live-count-diagnostic-v13-envelopes-once-2026-10-24.md：HTTP400／JSON_ERROR／InvalidParameter，1批计数、0Chat、零重试；正常取消释放，LLMUse0。已取得特定模型text总字节容量事实，后续修复和新输入不续用此许可。
