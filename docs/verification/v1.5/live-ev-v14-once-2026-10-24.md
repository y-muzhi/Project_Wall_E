# V1.5 explicitly bounded EV execution

Human authorization required before this command. At most 78 count batches and 24 Chat calls across 26 fixed cases; worst-case Chat total 3342336. Per Chat input131072/output8192/total139264, reserve1024, zero retries. No model judge. Normal databases/count audits retained, including failure.

Release: ac9c887f0dc52482d7cc329a0faaeb2cfd2e3f69c8e6f89df90f5d16b7a21d14; input source: a6b92ffe1975035afbc2ba171c24ee4127bd1e96cdda82675c5d003b10b28a6d; runner source: 14423b11bb44afe2f3e8723e41409e9010820a963e70bd730552707f51f45fbb; application source: 4303c22798c16303c9f27bc292596454bcbc595ae089db8e2e35dc13429a258c; manifest: 0353339a82a64183da576c460b538df3c97edd9c7d59d2dd518898ed5557b76b; profile: 61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e; model: deepseek-v4-1-flash-260910

## movie/discuss-initial

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=9e398845e838ade854da4ebf859a55da66d3cd6aa483c873bd8e449c70481019.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=8292, output_tokens=2560, finish_reason=stop, duration_ms=16106, actual_total_tokens=10852, actual_cached_tokens=6144, actual_text_counts=[7942,347,98,1,1,1,90,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 966554cad7e1481ca9982de049186363: phase=SUCCEEDED; exact eight counts=[7942, 347, 98, 1, 1, 1, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/discuss-long-preference

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=14; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=d5154916fd0d4ecb6445a6976efad2cab5a4746f68cf05f945e3ba45789d2043.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=9012, output_tokens=2337, finish_reason=stop, duration_ms=13113, actual_total_tokens=11349, actual_cached_tokens=7936, actual_text_counts=[7942,1067,135,1,1,1,773,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit a76d17f783134191b3ce1e8edf3834cd: phase=SUCCEEDED; exact eight counts=[7942, 1067, 135, 1, 1, 1, 773, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/discuss-correction

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=d4be3213d876f43fa7aee6bfbdccdb3486fd55e00ee1b1ff83095ed5c88239a5.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=8308, output_tokens=2466, finish_reason=stop, duration_ms=14972, actual_total_tokens=10774, actual_cached_tokens=8192, actual_text_counts=[7942,363,114,1,1,1,90,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 4b012ba71a9f47ac9ef501c3ec008703: phase=SUCCEEDED; exact eight counts=[7942, 363, 114, 1, 1, 1, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/discuss-decline

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=154f38e10fde4b5f389670e01108bdfd889a3f391f205b19d49d3d1c67c91386.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=8418, output_tokens=2273, finish_reason=stop, duration_ms=14493, actual_total_tokens=10691, actual_cached_tokens=7936, actual_text_counts=[7942,473,94,1,1,1,175,180]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 0df34a1ee70f441cac7a8b188ca2cb7c: phase=SUCCEEDED; exact eight counts=[7942, 473, 94, 1, 1, 1, 175, 180]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/document-generate

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=33b02a8145ae27dcccbcd2591b92510007c53111eb4ed50b327d569d604945cc.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=4835, output_tokens=1717, finish_reason=stop, duration_ms=10326, actual_total_tokens=6552, actual_cached_tokens=0, actual_text_counts=[4313,519,133,140,1,1,90,135]; primary=APPLIED; progress=REJECTED.

Count audit e94e4638736149fc93c987719c7db2f4: phase=SUCCEEDED; exact eight counts=[4313, 519, 133, 140, 1, 1, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/document-local-revise

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=222b060b1b2eafef07c77f2ee56213db71f10d737e11e9a16064ea5cecf02fc7.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=5294, output_tokens=352, finish_reason=stop, duration_ms=2817, actual_total_tokens=5646, actual_cached_tokens=0, actual_text_counts=[4320,971,126,140,433,32,90,135]; primary=APPLIED; progress=APPLIED.

Count audit 09c1afca60734babb6375b9ae4c0d1d5: phase=SUCCEEDED; exact eight counts=[4320, 971, 126, 140, 433, 32, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/document-long-specification

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=4a618a2f76a01cdcf1c41ea030dc05d12d8e37019e6d31d28144f5f3ccd4ed24.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=FAILED, validation_status=NOT_STARTED, input_tokens=29608, output_tokens=8192, finish_reason=length, duration_ms=39541, actual_total_tokens=37800, actual_cached_tokens=4224, actual_text_counts=[4313,25292,4487,20559,1,1,90,135]; primary=NOT_APPLIED; progress=NOT_REQUESTED.

Count audit 9121ae007d5840f59d43480d57bd7b0c: phase=SUCCEEDED; exact eight counts=[4313, 25292, 4487, 20559, 1, 1, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/proposals-table-row

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=3d7a4269e43b50b77d850758f621fe5a9039887c1acaf26d44126f556ecca814.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=6135, output_tokens=882, finish_reason=stop, duration_ms=5880, actual_total_tokens=7017, actual_cached_tokens=0, actual_text_counts=[5428,704,141,1,261,59,90,135]; primary=APPLIED; progress=APPLIED.

Count audit 694ad3aa8a2440ac84f7fcbd00accca7: phase=SUCCEEDED; exact eight counts=[5428, 704, 141, 1, 261, 59, 90, 135]; failure_reason=None; http_status=None.

Program postcondition: PASSED: normal ACCEPTED row completion; result=BATCH_APPLIED.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/proposals-user-edit

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=3d7a4269e43b50b77d850758f621fe5a9039887c1acaf26d44126f556ecca814.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=6135, output_tokens=452, finish_reason=stop, duration_ms=3762, actual_total_tokens=6587, actual_cached_tokens=6016, actual_text_counts=[5428,704,141,1,261,59,90,135]; primary=APPLIED; progress=NOT_REQUESTED.

Count audit 872bac6caa8a4b49965a8b97c42f6529: phase=SUCCEEDED; exact eight counts=[5428, 704, 141, 1, 261, 59, 90, 135]; failure_reason=None; http_status=None.

Program postcondition: PASSED: normal EDITED row completion; result=BATCH_APPLIED.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/proposals-stale-original

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=3d7a4269e43b50b77d850758f621fe5a9039887c1acaf26d44126f556ecca814.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=6135, output_tokens=578, finish_reason=stop, duration_ms=5032, actual_total_tokens=6713, actual_cached_tokens=6016, actual_text_counts=[5428,704,141,1,261,59,90,135]; primary=APPLIED; progress=NOT_REQUESTED.

Count audit a00215ae00914cc8a9a8a01dc83c96a2: phase=SUCCEEDED; exact eight counts=[5428, 704, 141, 1, 261, 59, 90, 135]; failure_reason=None; http_status=None.

Program postcondition: PASSED: isolated stale-original injection; result=TARGET_STALE.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/analysis-local-impact

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=eb94225ee58e68cd3a2f355fa2ee2df93840c9c1e0f4b00fcdf7a0a1cb99681e.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=4845, output_tokens=1736, finish_reason=stop, duration_ms=11148, actual_total_tokens=6581, actual_cached_tokens=0, actual_text_counts=[4017,825,125,1,426,31,90,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 5c5a41f085d1450a8c9c5811a0753b96: phase=SUCCEEDED; exact eight counts=[4017, 825, 125, 1, 426, 31, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/analysis-old-new

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=abad11b66a780e4a22c5a87016610a37cef655f76ff6725c6bed80cb112700cf.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=5235, output_tokens=2170, finish_reason=stop, duration_ms=13493, actual_total_tokens=7405, actual_cached_tokens=0, actual_text_counts=[4003,1229,106,1,849,31,90,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit c0f745999f504cf68eeb438faeabe2fe: phase=SUCCEEDED; exact eight counts=[4003, 1229, 106, 1, 849, 31, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/analysis-required-over-budget

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FAILED; count batches=2; Chat=0; status=FAILED; error=CONTEXT_LIMIT_EXCEEDED; user SHA256=2fd3a36b53e62e75df9fa2b1445c681613d9c89c9583fbc8de703fc639761a6b.

LLMUse summary: none; primary=None; progress=None.

Count audit 2a1bacb98d0b4f97a7cbeeb1306e883d: phase=SUCCEEDED; exact eight counts=[4017, 153785, 134, 1, 153377, 31, 90, 135]; failure_reason=None; http_status=None.

Count audit 75347d60a1c34621905c442a207e90b8: phase=SUCCEEDED; exact eight counts=[4017, 153757, 134, 1, 153377, 1, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/discuss-initial

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a830d72ab39ee2ed1e5671f657646b343171274c4d0d552ac1eecb156974a715.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=8295, output_tokens=2089, finish_reason=stop, duration_ms=15131, actual_total_tokens=10384, actual_cached_tokens=6144, actual_text_counts=[7942,350,98,1,1,1,93,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 293e74e1e0c4439fb2691a755e12f290: phase=SUCCEEDED; exact eight counts=[7942, 350, 98, 1, 1, 1, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/discuss-long-preference

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=14; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=f269342b52082de7f239f21e43cb814e1c1f9274b86b0270106d406a41504ca8.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=9019, output_tokens=1767, finish_reason=stop, duration_ms=11791, actual_total_tokens=10786, actual_cached_tokens=6144, actual_text_counts=[7942,1074,135,1,1,1,780,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 292f9257dc964942974574e971220f11: phase=SUCCEEDED; exact eight counts=[7942, 1074, 135, 1, 1, 1, 780, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/discuss-correction

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=6f8dfa29f89e93bb0ac3ca2fac57f155c3fb2bcab8f52970d49f712146a284ba.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=8310, output_tokens=2466, finish_reason=stop, duration_ms=17228, actual_total_tokens=10776, actual_cached_tokens=8192, actual_text_counts=[7942,365,113,1,1,1,93,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 70b38c3f17d24787a5c887297f51feff: phase=SUCCEEDED; exact eight counts=[7942, 365, 113, 1, 1, 1, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/discuss-decline

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=173bce4538640616c1bdaea022bd587823da6c0849892b022dc7e77ad5e25746.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=8421, output_tokens=1770, finish_reason=stop, duration_ms=10904, actual_total_tokens=10191, actual_cached_tokens=7936, actual_text_counts=[7942,476,94,1,1,1,178,180]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 520e216d9e4b4392b079416d54470bb8: phase=SUCCEEDED; exact eight counts=[7942, 476, 94, 1, 1, 1, 178, 180]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/document-generate

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=342b4cf2a2b9b49c9dc71dbd3bd18f47531af76ab73f50cf0dfbb2f7835905f4.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=FAILED, input_tokens=4844, output_tokens=2270, finish_reason=stop, duration_ms=12301, actual_total_tokens=7114, actual_cached_tokens=4480, actual_text_counts=[4313,528,139,140,1,1,93,135]; primary=APPLIED; progress=REJECTED.

Count audit 154e557434b343be923dab1dfc76bcb0: phase=SUCCEEDED; exact eight counts=[4313, 528, 139, 140, 1, 1, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/document-local-revise

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=5fbe6db8ea044acf8e1753fe4211defe15c559fd027f011ed7a6720c35d0c17a.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=5302, output_tokens=396, finish_reason=stop, duration_ms=3483, actual_total_tokens=5698, actual_cached_tokens=4480, actual_text_counts=[4320,979,127,140,437,32,93,135]; primary=APPLIED; progress=APPLIED.

Count audit d60ffb3593b6400f9bad6daec5074fc9: phase=SUCCEEDED; exact eight counts=[4320, 979, 127, 140, 437, 32, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/document-long-specification

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=460db58c4b14f50fd02eab7eeeb4890f3d6b4610793e178f6f3d230eb37527f3.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=FAILED, validation_status=NOT_STARTED, input_tokens=29998, output_tokens=8192, finish_reason=length, duration_ms=41912, actual_total_tokens=38190, actual_cached_tokens=24576, actual_text_counts=[4313,25682,4874,20559,1,1,93,135]; primary=NOT_APPLIED; progress=NOT_REQUESTED.

Count audit fdcbca42a1e34bdd9fb275e8a44c427e: phase=SUCCEEDED; exact eight counts=[4313, 25682, 4874, 20559, 1, 1, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/proposals-table-row

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a128dfabaf94da66d7590d498b6a00f92e487d165ba43860a7d322c171aa1cfe.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=6143, output_tokens=465, finish_reason=stop, duration_ms=3824, actual_total_tokens=6608, actual_cached_tokens=5376, actual_text_counts=[5428,712,142,1,265,59,93,135]; primary=APPLIED; progress=NOT_REQUESTED.

Count audit a25de9705f874b78ad5adf18c72498ea: phase=SUCCEEDED; exact eight counts=[5428, 712, 142, 1, 265, 59, 93, 135]; failure_reason=None; http_status=None.

Program postcondition: PASSED: normal ACCEPTED row completion; result=BATCH_APPLIED.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/proposals-user-edit

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a128dfabaf94da66d7590d498b6a00f92e487d165ba43860a7d322c171aa1cfe.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=6143, output_tokens=985, finish_reason=stop, duration_ms=7196, actual_total_tokens=7128, actual_cached_tokens=6016, actual_text_counts=[5428,712,142,1,265,59,93,135]; primary=APPLIED; progress=APPLIED.

Count audit 1b771c94c3f045c2b59eb3bdc6c7c794: phase=SUCCEEDED; exact eight counts=[5428, 712, 142, 1, 265, 59, 93, 135]; failure_reason=None; http_status=None.

Program postcondition: PASSED: normal EDITED row completion; result=BATCH_APPLIED.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/proposals-stale-original

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a128dfabaf94da66d7590d498b6a00f92e487d165ba43860a7d322c171aa1cfe.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=6143, output_tokens=467, finish_reason=stop, duration_ms=3864, actual_total_tokens=6610, actual_cached_tokens=6016, actual_text_counts=[5428,712,142,1,265,59,93,135]; primary=APPLIED; progress=NOT_REQUESTED.

Count audit f5a9c6a5e278411fb6026fa682c56877: phase=SUCCEEDED; exact eight counts=[5428, 712, 142, 1, 265, 59, 93, 135]; failure_reason=None; http_status=None.

Program postcondition: PASSED: isolated stale-original injection; result=TARGET_STALE.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/analysis-local-impact

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=c243707cc9294acd0904c4d97a17aed93d1414421aaa8f78e23e0b67599a8e5d.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=4852, output_tokens=1822, finish_reason=stop, duration_ms=12997, actual_total_tokens=6674, actual_cached_tokens=3968, actual_text_counts=[4017,832,125,1,430,31,93,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 67b5da6e8f0b418c9f3a5b2239896129: phase=SUCCEEDED; exact eight counts=[4017, 832, 125, 1, 430, 31, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/analysis-old-new

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a3293f1c269697e7fd602f1bdca22a8700ac48d7cdf26de993f1da00f4a0f91d.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=5246, output_tokens=1948, finish_reason=stop, duration_ms=12327, actual_total_tokens=7194, actual_cached_tokens=3968, actual_text_counts=[4003,1240,106,1,857,31,93,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit a738df365f8241159ddf5dd8544f262a: phase=SUCCEEDED; exact eight counts=[4003, 1240, 106, 1, 857, 31, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/analysis-required-over-budget

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FAILED; count batches=2; Chat=0; status=FAILED; error=CONTEXT_LIMIT_EXCEEDED; user SHA256=5f9afa8c56db8536de2c8e3cb724317378d1a48438f3a0493d2262b848b4c721.

LLMUse summary: none; primary=None; progress=None.

Count audit cfb87790618a4b7f91c11712a4b742ff: phase=SUCCEEDED; exact eight counts=[4017, 153788, 134, 1, 153377, 31, 93, 135]; failure_reason=None; http_status=None.

Count audit d27dfd187b834acca392e40a09bd1c1f: phase=SUCCEEDED; exact eight counts=[4017, 153760, 134, 1, 153377, 1, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

Actual aggregate counts=28; Chat=24. No retries.
