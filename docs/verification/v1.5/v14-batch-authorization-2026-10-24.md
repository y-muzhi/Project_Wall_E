# V1.5 v14一次技术及条件EV批次授权

2026-10-24T22:02:28.604300+08:00（Asia/Hong_Kong）。用户明确“授权技术及条件通过后的26样本（推荐）”，对应call_c96640b078ad457d8658fa4efd87c827。

先新独占data/v15-observation-20261024-v14-once执行最多1批计数＋1次Chat，只有同v14技术LIVE、usage和首轮parse／validation全成功后，才执行新独占data/v15-ev-20261024-v14-once的两领域26固定样本（最多78计数／24Chat，必要全文两份0Chat）。

整批最多79计数／25Chat；每次Chat输入131072／输出8192／总139264，整批Chat总Token3481600。零重试，不自动换输入／模型／版本；未知或计数异常立即停止，技术结构不通过结束整批，原结果保留，不动用户库或服务，不调用模型裁判，不做Git写操作。旧v13许可已结束，本次是独立新许可。

release=ac9c887f0dc52482d7cc329a0faaeb2cfd2e3f69c8e6f89df90f5d16b7a21d14；profile=61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e；model=deepseek-v4-1-flash-260910；backend/app SHA256=3820e7dad052feade4125d928a9869fea23fce9fdd0c9cbfb20dbd597e3878e2。相关13文件129 passed／11子场景，定向5项通过。

- tools/prepare-v15-evaluation.py：a6b92ffe1975035afbc2ba171c24ee4127bd1e96cdda82675c5d003b10b28a6d
- tools/run-v15-evaluation.py：14423b11bb44afe2f3e8723e41409e9010820a963e70bd730552707f51f45fbb
- tools/count-v15-evaluation-once.py：4425ecfed8a926aec027e0e5c1c0081e0ca2aa2f208a05cab21e06f07195695e
- docs/design/v1.5/WALL-E.后端设计文档_V_1.5.md：8c818b009879ce902b9ef2e2692028013437cc47a801d32b5ac7e484c38e80f0
- backend/resources/v14/manifest.json：0353339a82a64183da576c460b538df3c97edd9c7d59d2dd518898ed5557b76b

必要全文user与已实测U153785原2fd3a36b…相同，省去额外独立纯计数；技术及每份EV仍须新release的实际8项收据。凭证只由CLI安全读取.env.local，值不记录。两个新槽及报告未占用；技术即将执行，EV条件尚未成立。

技术阶段已结束：1计数／1Chat，LIVE_VERIFIED，call／parse／validation均SUCCEEDED，progress APPLIED／根IDLE／0文档；实际输入8287／输出1965／总10252／缓存0／gap3。正常原审计只读重验通过，进入26EV条件成立。下一槽data/v15-ev-20261024-v14-once及报告live-ev-v14-once-2026-10-24.md，只执行固定26样本，最多78计数／24Chat，零重试；整批上限不变。

本批已完整结束，技术＋26EV全部各一次完成：29计数／25Chat，输入213255／输出52317／总265572／缓存133760，零重试。实际19个EV校验成功、3个分量失败、2个截断与2个超限负向边界，6个候选后处理PASSED；语义待人工审阅。报告live-verification-v14-once-2026-10-24.md。未用最大次数不得复用到新槽或修复版本。
