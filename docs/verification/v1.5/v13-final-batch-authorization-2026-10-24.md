# V1.5 v13完整条件批次授权

2026-10-24T15:33:48.223345+08:00（Asia/Hong_Kong）。用户明确答复“授权完整条件批次（推荐）”，对应本线程call_318584af86c846b7bea8f8f8d4c6fdb3问题。

阶段1：新独占v15-count-gate-20261024-v13-final-once，最多1批Tokenization、0Chat；必须取得精确计数且必要全文实际超Token预算才进入阶段2，否则结束。

阶段2：新独占v15-observation-20261024-v13-final-once，最多1批计数＋1Chat；同v13准入／usage及首轮结构通过才进入阶段3，否则结束。

阶段3：新独占v15-ev-20261024-v13-final-once，两领域26个固定样本，最多78计数／24Chat，必要全文两份0Chat。

整批最多80计数／25Chat；每次Chat输入≤131072、输出≤8192、总≤139264；整批Chat总Token≤3481600。零重试，不自动换输入／模型／资源版本；未知或计数异常即停止，保留旧结果和正常新库审计，不动用户库／服务，不调用模型裁判，不提交推送。许可不得用于失败后的另一槽重试。

固定release=eeb7925e52dbecb521ad19a448ba7ae24be4aac63ff8d5b4a0a384ba534c4a68；profile=61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e；model=deepseek-v4-1-flash-260910；backend/app SHA256=67a8f51d3c96b5949e9204c2288680009330dfb3baee31a454d2fb1530178050。

固定输入／工具／正式BE及manifest已逐项核对：

- tools/prepare-v15-evaluation.py：a6b92ffe1975035afbc2ba171c24ee4127bd1e96cdda82675c5d003b10b28a6d
- tools/run-v15-evaluation.py：14423b11bb44afe2f3e8723e41409e9010820a963e70bd730552707f51f45fbb
- tools/count-v15-evaluation-once.py：4425ecfed8a926aec027e0e5c1c0081e0ca2aa2f208a05cab21e06f07195695e
- docs/design/v1.5/WALL-E.后端设计文档_V_1.5.md：fd231a9d32300bce072f07d628b617ff449a18e6b012e35999eed7f245030be8
- backend/resources/v13/manifest.json：6ca926d0aa0954ec2dafc19225a7c65e21bdae1b6db99054667b6957436f8e2d

所有新槽／报告未占用，8000／5173无监听；凭证仅由显式CLI从.env.local安全读取，值不记录。阶段1即将执行；阶段2／3条件尚未成立，未执行。

阶段1已单次结束（CLI退出0）：1计数、0Chat；精确八项3907／153785／134／1／153377／31／90／135，预计输入158716>131072，正常SUCCEEDED摘要收据（raw_omitted_reason=AUDIT_CAPACITY）、run正常取消／根IDLE／LLMUse0。只读重新校验模型／请求／文本摘要及计数通过，进入阶段2条件成立。阶段2即将执行唯一1计数＋1Chat；阶段3仍未准入，不提前发送。

本批按条件结束：阶段2技术LIVE但首轮validation FAILED，阶段3未执行；总2计数／1Chat，实际Chat总10049。原许可已结束，未用上限不能用于修复后的版本或新槽。详见live-verification-v13-final-once-2026-10-24.md。
