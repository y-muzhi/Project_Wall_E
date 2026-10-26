# V1.5 one count-only diagnostic

Requires a new explicit authorization. Maximum one Tokenization batch, zero Chat, zero retries; fixed movie/analysis-required-over-budget input. Preserve the claimed slot and original normal evidence on failure or interruption.

release=eeb7925e52dbecb521ad19a448ba7ae24be4aac63ff8d5b4a0a384ba534c4a68; manifest=6ca926d0aa0954ec2dafc19225a7c65e21bdae1b6db99054667b6957436f8e2d; profile=61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e; tool SHA256=c8ed6c16d6c179cce40c8d2500d91945afd717c2d3168d4401b8fbc8d3983e98.

Count slot claimed; journal=e1856018717f477b87e237eb25adbb85; user SHA256=b692bbacc1ff6504c6481fe89413dc1834e0cc0d8e72eb0fe9f10ef61393a968. No repeated send after unknown outcome.

Stopped: HTTP_STATUS; HTTP status=400; Chat=0. No retry.

Private diagnostic saved; body_state=JSON_ERROR; category=PARAMETER; code=InvalidParameter; parameter=None; request_id=0217928249668159255aa03547266d00c3fa3dce78057f16c0edf; fields=['code', 'message', 'param', 'type']. Provider message is private journal data, not copied here.

Normal isolated run release=GUIDE_CANCELLED. No Chat was dispatched.

后续只读核对：run=CANCELLED，根工作占用=IDLE，LLMUse=0。正常私有错误说明确认本次单批text UTF-8合计上限800000字节、实际1074366字节；离线逐段重算一致，JSON请求体1092341字节为另一指标。这里只记录已证实的容量事实，不复制错误正文；旧v12原因不据此改写。该许可已消耗结束，新修订输入不得复用本槽或许可。
