# V1.5 资源批次v15技术及条件EV授权

2026-10-24T23:29:21.291775+08:00（Asia/Hong_Kong）。用户明确“授权技术及条件通过后的26样本（推荐）”，对应call_f695bfab5bdc4f9a8674ed52df817e17。

先新独占data/v15-observation-20261024-v15-once执行最多1批计数＋1次Chat，只有同v15技术LIVE、usage及首轮parse／validation成功后，才执行data/v15-ev-20261024-v15-once两领域26固定样本（最多78计数／24Chat，其中必要全文两份0Chat）。

整批最多79计数／25Chat；每次输入131072／输出8192／总139264，整批Chat总3481600。零重试，不自动换输入／模型／版本；未知、计数异常或失败传输即停止，首轮结构失败结束整批。原结果保留，不动用户库／服务，不调用模型裁判，不做Git写操作。此为独立新许可，旧v14许可不续用。

release=5ced9443c445aa10330e906a875fd4dafe69b6ebe0eb5e40179251b5eefb5d97；profile=61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e；model=deepseek-v4-1-flash-260910；backend/app SHA256=9cf0a135b6232d593716a0cf576d71c285756265ba6a07ad6e156660a80358f5。离线相关108项及定向5项通过。

- tools/prepare-v15-evaluation.py：a6b92ffe1975035afbc2ba171c24ee4127bd1e96cdda82675c5d003b10b28a6d
- tools/run-v15-evaluation.py：21bfb89a6933de8ac25b2dd125682352dcbc231018ebc38b69fa966d921545a3
- tools/count-v15-evaluation-once.py：4425ecfed8a926aec027e0e5c1c0081e0ca2aa2f208a05cab21e06f07195695e
- docs/design/v1.5/WALL-E.后端设计文档_V_1.5.md：9f7e6476861e8d954fc6be675973c6e829988b2c582a107367b3d764fb90bcdd
- backend/resources/v15/manifest.json：a8c5087236d8e4b4b40d62a92643832fe37cc2b5e426725f1ddde7d5670abc40

两个新槽及报告未占用，8000／5173无监听。凭证只由CLI从.env.local安全读取，值不记录。技术即将执行，EV前置条件尚未成立。

技术阶段已单次结束：1计数／1Chat、LIVE_VERIFIED，call／parse／validation全成功，progress APPLIED／根IDLE／0文档；实际输入8408／输出2244／总10652／缓存0／gap3。正常审计只读重验通过，26EV条件成立。下一步唯一执行data/v15-ev-20261024-v15-once，最多78计数／24Chat，整批上限不变，零重试，不改被测源码或版本。

本批已完整结束：技术＋26EV合计29计数／25Chat，实际总Chat Token=265615，零重试。22个正常EV返回全部程序校验成功，两真实截断不半写、两超限0Chat、六候选后处理PASSED。原v14三项对应样本程序复验通过；人工语义待审。报告live-verification-v15-once-2026-10-24.md。剩余上限不得再次执行或用于新版本。
