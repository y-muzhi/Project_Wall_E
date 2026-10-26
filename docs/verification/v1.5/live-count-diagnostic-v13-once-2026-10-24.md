# V1.5 one count-only diagnostic

Requires a new explicit authorization. Maximum one Tokenization batch, zero Chat, zero retries; fixed movie/analysis-required-over-budget input. Preserve the claimed slot and original normal evidence on failure or interruption.

release=eeb7925e52dbecb521ad19a448ba7ae24be4aac63ff8d5b4a0a384ba534c4a68; manifest=6ca926d0aa0954ec2dafc19225a7c65e21bdae1b6db99054667b6957436f8e2d; profile=61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e; tool SHA256=3042e409c7339338f1e87c7d19cc135bc0c68939475ceefbe77321ffc5f4f3de.

Count slot claimed; journal=a309cb5b421b41a0afe062c99a36f57a; user SHA256=b692bbacc1ff6504c6481fe89413dc1834e0cc0d8e72eb0fe9f10ef61393a968. No repeated send after unknown outcome.

Stopped: HTTP_STATUS; HTTP status=400; Chat=0. No retry.

Normal isolated run release=GUIDE_CANCELLED. No Chat was dispatched.

## 正常状态只读核对

实际1计数批、供应方HTTP400，未取得精确计数；finished FAILED／HTTP_STATUS／400，Chat0／LLMUse0。正常取消后run CANCELLED／FINISHED，根IDLE。本许可已消耗结束，原槽及正常审计保留；不推断旧v12同因，不称超预算门限通过。

核对[官方Tokenization文档](https://docs.volcengine.com/docs/ark/tokenization-api?lang=en)：text可为字符串或字符串数组；公开字段说明未给出能确定本次400原因的上限。未按猜测调整预算、拆分计数或更换模型。未保存供应方错误体，无法据本条进一步确定参数原因；不得自动再次调用。
