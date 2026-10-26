# V1.5 one count-only diagnostic

Requires a new explicit authorization. Maximum one Tokenization batch, zero Chat, zero retries; fixed movie/analysis-required-over-budget input. Preserve the claimed slot and original normal evidence on failure or interruption.

release=eeb7925e52dbecb521ad19a448ba7ae24be4aac63ff8d5b4a0a384ba534c4a68; manifest=6ca926d0aa0954ec2dafc19225a7c65e21bdae1b6db99054667b6957436f8e2d; profile=61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e; tool SHA256=88277ed311357f9abed6825b7baf80ce189b6e690249872aa36b4ef159d57c25.

Count slot claimed; journal=6570cb627aeb415498a62754be9f4167; user SHA256=b692bbacc1ff6504c6481fe89413dc1834e0cc0d8e72eb0fe9f10ef61393a968. No repeated send after unknown outcome.

Stopped: HTTP_STATUS; HTTP status=400; Chat=0. No retry.

Private diagnostic saved; body_state=NO_ERROR_OBJECT; category=HTTP_ERROR; code=None; parameter=None; request_id=021792823940314a6cdd8247c48d753298cd4bcf5eec90e206f83. Provider message is private journal data, not copied here.

Normal isolated run release=GUIDE_CANCELLED. No Chat was dispatched.

## 实际结果与诊断覆盖缺口

本次1批真实计数／0Chat、零重试；HTTP400，body_state=NO_ERROR_OBJECT，提供请求ID021792823940314a6cdd8247c48d753298cd4bcf5eec90e206f83。说明未取得，不能推断具体参数原因或旧v12同因。正常只读核对run CANCELLED、根IDLE、LLMUse0。本许可已结束，原槽保留。

本结果暴露解析器只识别嵌套error对象。后续离线扩展顶层message、detail字符串／验证列表及ResponseMetadata.Error等结构；不补写本槽缺失数据，不自动再次发送。后续静态及专项证据另记，不能改称本次已经定位。
