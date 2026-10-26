# V1.5 explicitly bounded EV execution

Human authorization required before this command. At most 78 count batches and 24 Chat calls across 26 fixed cases; worst-case Chat total 3342336. Per Chat input131072/output8192/total139264, reserve1024, zero retries. No model judge. Normal databases/count audits retained, including failure.

Release: ad5e45c5e2373ece410d699c886e887c8179ac5303368c6e2fbc668341110a2e; input source: 6b0de89db48479ef770d6cbc9d4df00a10ff0f748548359f8c72402d4066bdd3; runner source: 2581f49dc32f8b2429e697b0659ab6c72976b80e8452837d082ae2c49b5ab834; application source: 24e8458a7c276e8bd5522d10fa59f28ad6d06bddc164bfd30dfbac08ac8c008d; manifest: 3db3a635d5c639d6e1406e717bd7e84d380e70cb4796464fea101477a5810312; profile: 61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e; model: deepseek-v4-1-flash-260910

## movie/discuss-initial

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=9e398845e838ade854da4ebf859a55da66d3cd6aa483c873bd8e449c70481019.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=7417, output_tokens=1972, finish_reason=stop, duration_ms=13524, actual_total_tokens=9389, actual_cached_tokens=7040, actual_text_counts=[7067,347,98,1,1,1,90,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit d960a120b8e24f489ffb735ed33fee76: phase=SUCCEEDED; exact eight counts=[7067, 347, 98, 1, 1, 1, 90, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/discuss-long-preference

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=14; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=d5154916fd0d4ecb6445a6976efad2cab5a4746f68cf05f945e3ba45789d2043.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=8137, output_tokens=1318, finish_reason=stop, duration_ms=7631, actual_total_tokens=9455, actual_cached_tokens=7040, actual_text_counts=[7067,1067,135,1,1,1,773,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 45a70a809a7544168feace2ce257e320: phase=SUCCEEDED; exact eight counts=[7067, 1067, 135, 1, 1, 1, 773, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/discuss-correction

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=d4be3213d876f43fa7aee6bfbdccdb3486fd55e00ee1b1ff83095ed5c88239a5.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=7433, output_tokens=1359, finish_reason=stop, duration_ms=9268, actual_total_tokens=8792, actual_cached_tokens=7296, actual_text_counts=[7067,363,114,1,1,1,90,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 80f2dfa289494028b5c9b7edb5a036a2: phase=SUCCEEDED; exact eight counts=[7067, 363, 114, 1, 1, 1, 90, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/discuss-decline

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=154f38e10fde4b5f389670e01108bdfd889a3f391f205b19d49d3d1c67c91386.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=7543, output_tokens=2265, finish_reason=stop, duration_ms=15139, actual_total_tokens=9808, actual_cached_tokens=7040, actual_text_counts=[7067,473,94,1,1,1,175,180]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 5d520443a2be4d88bda3b2ebdae5ab90: phase=SUCCEEDED; exact eight counts=[7067, 473, 94, 1, 1, 1, 175, 180].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/document-generate

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=33b02a8145ae27dcccbcd2591b92510007c53111eb4ed50b327d569d604945cc.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=3960, output_tokens=1907, finish_reason=stop, duration_ms=10780, actual_total_tokens=5867, actual_cached_tokens=0, actual_text_counts=[3438,519,133,140,1,1,90,135]; primary=APPLIED; progress=REJECTED.

Count audit 0ee444a49d1444c1a9e067888a135e83: phase=SUCCEEDED; exact eight counts=[3438, 519, 133, 140, 1, 1, 90, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/document-local-revise

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=222b060b1b2eafef07c77f2ee56213db71f10d737e11e9a16064ea5cecf02fc7.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=4419, output_tokens=350, finish_reason=stop, duration_ms=3001, actual_total_tokens=4769, actual_cached_tokens=0, actual_text_counts=[3445,971,126,140,433,32,90,135]; primary=APPLIED; progress=REJECTED.

Count audit 847d82b013744067aa2efb4b47fbf90e: phase=SUCCEEDED; exact eight counts=[3445, 971, 126, 140, 433, 32, 90, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/document-long-specification

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=ab62a652bc881f636c884777e097937c26d210be3bc2191a6b19451eb6998dd1.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=25310, output_tokens=1967, finish_reason=stop, duration_ms=14635, actual_total_tokens=27277, actual_cached_tokens=3328, actual_text_counts=[3438,21869,1064,20559,1,1,90,135]; primary=NOT_APPLIED; progress=APPLIED.

Count audit 854172561f054ded9db1c9c1bf29baa5: phase=SUCCEEDED; exact eight counts=[3438, 21869, 1064, 20559, 1, 1, 90, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/proposals-table-row

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=3d7a4269e43b50b77d850758f621fe5a9039887c1acaf26d44126f556ecca814.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=5260, output_tokens=1022, finish_reason=stop, duration_ms=7009, actual_total_tokens=6282, actual_cached_tokens=0, actual_text_counts=[4553,704,141,1,261,59,90,135]; primary=NOT_APPLIED; progress=REJECTED.

Count audit 64824cbf8f8849acaec96b6150eb1d29: phase=SUCCEEDED; exact eight counts=[4553, 704, 141, 1, 261, 59, 90, 135].

Program postcondition: NOT_EXERCISED: no saved candidate batch.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/proposals-user-edit

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=3d7a4269e43b50b77d850758f621fe5a9039887c1acaf26d44126f556ecca814.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=5260, output_tokens=605, finish_reason=stop, duration_ms=4989, actual_total_tokens=5865, actual_cached_tokens=5248, actual_text_counts=[4553,704,141,1,261,59,90,135]; primary=NOT_APPLIED; progress=NOT_REQUESTED.

Count audit 736d33b78fab4971a7f48c0ba3f50bd2: phase=SUCCEEDED; exact eight counts=[4553, 704, 141, 1, 261, 59, 90, 135].

Program postcondition: NOT_EXERCISED: no saved candidate batch.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/proposals-stale-original

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=3d7a4269e43b50b77d850758f621fe5a9039887c1acaf26d44126f556ecca814.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=5260, output_tokens=620, finish_reason=stop, duration_ms=4619, actual_total_tokens=5880, actual_cached_tokens=5248, actual_text_counts=[4553,704,141,1,261,59,90,135]; primary=NOT_APPLIED; progress=NOT_REQUESTED.

Count audit 3d832f8c048641d7843525c3eede68a6: phase=SUCCEEDED; exact eight counts=[4553, 704, 141, 1, 261, 59, 90, 135].

Program postcondition: NOT_EXERCISED: no saved candidate batch.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/analysis-local-impact

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=eb94225ee58e68cd3a2f355fa2ee2df93840c9c1e0f4b00fcdf7a0a1cb99681e.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=3970, output_tokens=1316, finish_reason=stop, duration_ms=9273, actual_total_tokens=5286, actual_cached_tokens=0, actual_text_counts=[3142,825,125,1,426,31,90,135]; primary=NOT_REQUESTED; progress=NOT_REQUESTED.

Count audit 9130559db5f6431fbfd57560b7644c12: phase=SUCCEEDED; exact eight counts=[3142, 825, 125, 1, 426, 31, 90, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/analysis-old-new

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=abad11b66a780e4a22c5a87016610a37cef655f76ff6725c6bed80cb112700cf.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=4360, output_tokens=1354, finish_reason=stop, duration_ms=10596, actual_total_tokens=5714, actual_cached_tokens=0, actual_text_counts=[3128,1229,106,1,849,31,90,135]; primary=NOT_REQUESTED; progress=REJECTED.

Count audit 7dbff4fcf98f4e6eb48ca9d460fa93cd: phase=SUCCEEDED; exact eight counts=[3128, 1229, 106, 1, 849, 31, 90, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/analysis-required-over-budget

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FAILED; count batches=1; Chat=0; status=FAILED; error=CONFIG_INVALID; user SHA256=b692bbacc1ff6504c6481fe89413dc1834e0cc0d8e72eb0fe9f10ef61393a968.

LLMUse summary: none; primary=None; progress=None.

Count audit b7025f19fc534de9b0e2cb587b43c04d: phase=FAILED; exact eight counts=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/discuss-initial

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a830d72ab39ee2ed1e5671f657646b343171274c4d0d552ac1eecb156974a715.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=7420, output_tokens=2110, finish_reason=stop, duration_ms=13548, actual_total_tokens=9530, actual_cached_tokens=7040, actual_text_counts=[7067,350,98,1,1,1,93,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit d567283530f94b92a96b33cfb3c60eca: phase=SUCCEEDED; exact eight counts=[7067, 350, 98, 1, 1, 1, 93, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/discuss-long-preference

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=14; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=f269342b52082de7f239f21e43cb814e1c1f9274b86b0270106d406a41504ca8.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=8144, output_tokens=2167, finish_reason=stop, duration_ms=12371, actual_total_tokens=10311, actual_cached_tokens=7040, actual_text_counts=[7067,1074,135,1,1,1,780,135]; primary=NOT_REQUESTED; progress=REJECTED.

Count audit 690309da653e4445a7d4d70bae4789e7: phase=SUCCEEDED; exact eight counts=[7067, 1074, 135, 1, 1, 1, 780, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/discuss-correction

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=6f8dfa29f89e93bb0ac3ca2fac57f155c3fb2bcab8f52970d49f712146a284ba.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=7435, output_tokens=1772, finish_reason=stop, duration_ms=14329, actual_total_tokens=9207, actual_cached_tokens=7296, actual_text_counts=[7067,365,113,1,1,1,93,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit e3ecb945bfdd494aaddb418de66d96d3: phase=SUCCEEDED; exact eight counts=[7067, 365, 113, 1, 1, 1, 93, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/discuss-decline

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=173bce4538640616c1bdaea022bd587823da6c0849892b022dc7e77ad5e25746.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=7546, output_tokens=2231, finish_reason=stop, duration_ms=15280, actual_total_tokens=9777, actual_cached_tokens=7040, actual_text_counts=[7067,476,94,1,1,1,178,180]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 45d09fcdfbb24728a04b3d92c8a0df8e: phase=SUCCEEDED; exact eight counts=[7067, 476, 94, 1, 1, 1, 178, 180].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/document-generate

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=342b4cf2a2b9b49c9dc71dbd3bd18f47531af76ab73f50cf0dfbb2f7835905f4.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=3969, output_tokens=1410, finish_reason=stop, duration_ms=9510, actual_total_tokens=5379, actual_cached_tokens=2048, actual_text_counts=[3438,528,139,140,1,1,93,135]; primary=APPLIED; progress=REJECTED.

Count audit dc00b36f59064670b6a346ce058a6e97: phase=SUCCEEDED; exact eight counts=[3438, 528, 139, 140, 1, 1, 93, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/document-local-revise

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=5fbe6db8ea044acf8e1753fe4211defe15c559fd027f011ed7a6720c35d0c17a.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=4427, output_tokens=404, finish_reason=stop, duration_ms=3423, actual_total_tokens=4831, actual_cached_tokens=2048, actual_text_counts=[3445,979,127,140,437,32,93,135]; primary=APPLIED; progress=REJECTED.

Count audit c93e68b5ac9d4375ad68fd4febe331fb: phase=SUCCEEDED; exact eight counts=[3445, 979, 127, 140, 437, 32, 93, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/document-long-specification

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=65c659cb2e83fcab603b6b93697d29e1bb535b80084b2c1a09f900ee2143f381.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=25315, output_tokens=1592, finish_reason=stop, duration_ms=11450, actual_total_tokens=26907, actual_cached_tokens=23936, actual_text_counts=[3438,21874,1066,20559,1,1,93,135]; primary=NOT_APPLIED; progress=APPLIED.

Count audit be08be9ce17c40699adc46a201b4ac87: phase=SUCCEEDED; exact eight counts=[3438, 21874, 1066, 20559, 1, 1, 93, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/proposals-table-row

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a128dfabaf94da66d7590d498b6a00f92e487d165ba43860a7d322c171aa1cfe.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=5268, output_tokens=667, finish_reason=stop, duration_ms=4465, actual_total_tokens=5935, actual_cached_tokens=4480, actual_text_counts=[4553,712,142,1,265,59,93,135]; primary=NOT_APPLIED; progress=NOT_REQUESTED.

Count audit d7ab9c12ff824a478f9d332223fff96a: phase=SUCCEEDED; exact eight counts=[4553, 712, 142, 1, 265, 59, 93, 135].

Program postcondition: NOT_EXERCISED: no saved candidate batch.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/proposals-user-edit

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a128dfabaf94da66d7590d498b6a00f92e487d165ba43860a7d322c171aa1cfe.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=5268, output_tokens=1068, finish_reason=stop, duration_ms=7234, actual_total_tokens=6336, actual_cached_tokens=5248, actual_text_counts=[4553,712,142,1,265,59,93,135]; primary=NOT_APPLIED; progress=REJECTED.

Count audit 1b4938de650f4e89976ff890c5ff65be: phase=SUCCEEDED; exact eight counts=[4553, 712, 142, 1, 265, 59, 93, 135].

Program postcondition: NOT_EXERCISED: no saved candidate batch.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/proposals-stale-original

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a128dfabaf94da66d7590d498b6a00f92e487d165ba43860a7d322c171aa1cfe.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=5268, output_tokens=498, finish_reason=stop, duration_ms=3702, actual_total_tokens=5766, actual_cached_tokens=5248, actual_text_counts=[4553,712,142,1,265,59,93,135]; primary=NOT_APPLIED; progress=NOT_REQUESTED.

Count audit c593b5f651d94576970bd1ec58d377ba: phase=SUCCEEDED; exact eight counts=[4553, 712, 142, 1, 265, 59, 93, 135].

Program postcondition: NOT_EXERCISED: no saved candidate batch.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/analysis-local-impact

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=c243707cc9294acd0904c4d97a17aed93d1414421aaa8f78e23e0b67599a8e5d.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=3977, output_tokens=1273, finish_reason=stop, duration_ms=9607, actual_total_tokens=5250, actual_cached_tokens=3072, actual_text_counts=[3142,832,125,1,430,31,93,135]; primary=NOT_REQUESTED; progress=NOT_REQUESTED.

Count audit 6ba2d81af3944ed4801119939d88ffe6: phase=SUCCEEDED; exact eight counts=[3142, 832, 125, 1, 430, 31, 93, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/analysis-old-new

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a3293f1c269697e7fd602f1bdca22a8700ac48d7cdf26de993f1da00f4a0f91d.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=4371, output_tokens=1646, finish_reason=stop, duration_ms=10564, actual_total_tokens=6017, actual_cached_tokens=3072, actual_text_counts=[3128,1240,106,1,857,31,93,135]; primary=NOT_REQUESTED; progress=REJECTED.

Count audit 6c080b5e21ee4f6786fec11bb3d5fdd1: phase=SUCCEEDED; exact eight counts=[3128, 1240, 106, 1, 857, 31, 93, 135].

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/analysis-required-over-budget

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FAILED; count batches=1; Chat=0; status=FAILED; error=CONFIG_INVALID; user SHA256=56fa2a4ba9a34356f83060a4864482fe189c17e16b1f7657622490844c4816b9.

LLMUse summary: none; primary=None; progress=None.

Count audit f729b221df1044b68ea7789add742b1e: phase=FAILED; exact eight counts=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

Actual aggregate counts=26; Chat=24. No retries.
