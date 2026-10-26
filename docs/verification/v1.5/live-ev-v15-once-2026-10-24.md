# V1.5 explicitly bounded EV execution

Human authorization required before this command. At most 78 count batches and 24 Chat calls across 26 fixed cases; worst-case Chat total 3342336. Per Chat input131072/output8192/total139264, reserve1024, zero retries. No model judge. Normal databases/count audits retained, including failure.

Release: 5ced9443c445aa10330e906a875fd4dafe69b6ebe0eb5e40179251b5eefb5d97; input source: a6b92ffe1975035afbc2ba171c24ee4127bd1e96cdda82675c5d003b10b28a6d; runner source: 21bfb89a6933de8ac25b2dd125682352dcbc231018ebc38b69fa966d921545a3; application source: 9e2e3728e5a2feb96459949950d98a146150478868a7088d081719a095039b49; manifest: a8c5087236d8e4b4b40d62a92643832fe37cc2b5e426725f1ddde7d5670abc40; profile: 61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e; model: deepseek-v4-1-flash-260910

## movie/discuss-initial

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=9e398845e838ade854da4ebf859a55da66d3cd6aa483c873bd8e449c70481019.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=8413, output_tokens=2023, finish_reason=stop, duration_ms=13580, actual_total_tokens=10436, actual_cached_tokens=8064, actual_text_counts=[8063,347,98,1,1,1,90,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 7a6146aafc1846cbba5178a79fccbeec: phase=SUCCEEDED; exact eight counts=[8063, 347, 98, 1, 1, 1, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/discuss-long-preference

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=14; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=d5154916fd0d4ecb6445a6976efad2cab5a4746f68cf05f945e3ba45789d2043.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=9133, output_tokens=1698, finish_reason=stop, duration_ms=10696, actual_total_tokens=10831, actual_cached_tokens=8064, actual_text_counts=[8063,1067,135,1,1,1,773,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit a04a613316a04ede8a223939d26b5660: phase=SUCCEEDED; exact eight counts=[8063, 1067, 135, 1, 1, 1, 773, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/discuss-correction

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=d4be3213d876f43fa7aee6bfbdccdb3486fd55e00ee1b1ff83095ed5c88239a5.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=8429, output_tokens=2204, finish_reason=stop, duration_ms=13254, actual_total_tokens=10633, actual_cached_tokens=8320, actual_text_counts=[8063,363,114,1,1,1,90,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit e3263db40ef24c959bc9b73a6a84f8eb: phase=SUCCEEDED; exact eight counts=[8063, 363, 114, 1, 1, 1, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/discuss-decline

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=154f38e10fde4b5f389670e01108bdfd889a3f391f205b19d49d3d1c67c91386.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=8539, output_tokens=1432, finish_reason=stop, duration_ms=12177, actual_total_tokens=9971, actual_cached_tokens=8064, actual_text_counts=[8063,473,94,1,1,1,175,180]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 15e5d7ce2ffa44a4b50bc7efb50b8dcc: phase=SUCCEEDED; exact eight counts=[8063, 473, 94, 1, 1, 1, 175, 180]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/document-generate

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=33b02a8145ae27dcccbcd2591b92510007c53111eb4ed50b327d569d604945cc.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=4956, output_tokens=1432, finish_reason=stop, duration_ms=8944, actual_total_tokens=6388, actual_cached_tokens=0, actual_text_counts=[4434,519,133,140,1,1,90,135]; primary=APPLIED; progress=APPLIED.

Count audit 420a633678bb49d281e716b154b932c6: phase=SUCCEEDED; exact eight counts=[4434, 519, 133, 140, 1, 1, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/document-local-revise

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=222b060b1b2eafef07c77f2ee56213db71f10d737e11e9a16064ea5cecf02fc7.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=5415, output_tokens=330, finish_reason=stop, duration_ms=2829, actual_total_tokens=5745, actual_cached_tokens=0, actual_text_counts=[4441,971,126,140,433,32,90,135]; primary=APPLIED; progress=APPLIED.

Count audit f36bf0e4b6344166949bffd6c797d90b: phase=SUCCEEDED; exact eight counts=[4441, 971, 126, 140, 433, 32, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/document-long-specification

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=4a618a2f76a01cdcf1c41ea030dc05d12d8e37019e6d31d28144f5f3ccd4ed24.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=FAILED, validation_status=NOT_STARTED, input_tokens=29729, output_tokens=8192, finish_reason=length, duration_ms=42738, actual_total_tokens=37921, actual_cached_tokens=4352, actual_text_counts=[4434,25292,4487,20559,1,1,90,135]; primary=NOT_APPLIED; progress=NOT_REQUESTED.

Count audit 2da263e167944fd88fcee5784b8723e3: phase=SUCCEEDED; exact eight counts=[4434, 25292, 4487, 20559, 1, 1, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/proposals-table-row

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=3d7a4269e43b50b77d850758f621fe5a9039887c1acaf26d44126f556ecca814.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=6256, output_tokens=794, finish_reason=stop, duration_ms=5554, actual_total_tokens=7050, actual_cached_tokens=0, actual_text_counts=[5549,704,141,1,261,59,90,135]; primary=APPLIED; progress=APPLIED.

Count audit 9cf67872056448fcb1ceb43bed040b3b: phase=SUCCEEDED; exact eight counts=[5549, 704, 141, 1, 261, 59, 90, 135]; failure_reason=None; http_status=None.

Program postcondition: PASSED: normal ACCEPTED row completion; result=BATCH_APPLIED.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/proposals-user-edit

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=3d7a4269e43b50b77d850758f621fe5a9039887c1acaf26d44126f556ecca814.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=6256, output_tokens=813, finish_reason=stop, duration_ms=5522, actual_total_tokens=7069, actual_cached_tokens=6144, actual_text_counts=[5549,704,141,1,261,59,90,135]; primary=APPLIED; progress=APPLIED.

Count audit d5f3fcd03b784de5993d228c7cdc44c0: phase=SUCCEEDED; exact eight counts=[5549, 704, 141, 1, 261, 59, 90, 135]; failure_reason=None; http_status=None.

Program postcondition: PASSED: normal EDITED row completion; result=BATCH_APPLIED.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/proposals-stale-original

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=3d7a4269e43b50b77d850758f621fe5a9039887c1acaf26d44126f556ecca814.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=6256, output_tokens=850, finish_reason=stop, duration_ms=5638, actual_total_tokens=7106, actual_cached_tokens=6144, actual_text_counts=[5549,704,141,1,261,59,90,135]; primary=APPLIED; progress=APPLIED.

Count audit 764bc48fbe104017935f4ca8ae046705: phase=SUCCEEDED; exact eight counts=[5549, 704, 141, 1, 261, 59, 90, 135]; failure_reason=None; http_status=None.

Program postcondition: PASSED: isolated stale-original injection; result=TARGET_STALE.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/analysis-local-impact

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=eb94225ee58e68cd3a2f355fa2ee2df93840c9c1e0f4b00fcdf7a0a1cb99681e.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=4966, output_tokens=1449, finish_reason=stop, duration_ms=9929, actual_total_tokens=6415, actual_cached_tokens=0, actual_text_counts=[4138,825,125,1,426,31,90,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit f3e0608bd0014a25b9ece3398843073e: phase=SUCCEEDED; exact eight counts=[4138, 825, 125, 1, 426, 31, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/analysis-old-new

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=abad11b66a780e4a22c5a87016610a37cef655f76ff6725c6bed80cb112700cf.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=5356, output_tokens=2015, finish_reason=stop, duration_ms=12242, actual_total_tokens=7371, actual_cached_tokens=0, actual_text_counts=[4124,1229,106,1,849,31,90,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit dc176b6113ea4b38b59fdfc9e024557e: phase=SUCCEEDED; exact eight counts=[4124, 1229, 106, 1, 849, 31, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## movie/analysis-required-over-budget

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FAILED; count batches=2; Chat=0; status=FAILED; error=CONTEXT_LIMIT_EXCEEDED; user SHA256=2fd3a36b53e62e75df9fa2b1445c681613d9c89c9583fbc8de703fc639761a6b.

LLMUse summary: none; primary=None; progress=None.

Count audit 4dedb2b63e504cdf8c8649f15540fa2a: phase=SUCCEEDED; exact eight counts=[4138, 153785, 134, 1, 153377, 31, 90, 135]; failure_reason=None; http_status=None.

Count audit 9c85997bb29041f5996f72b8b990730e: phase=SUCCEEDED; exact eight counts=[4138, 153757, 134, 1, 153377, 1, 90, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/discuss-initial

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a830d72ab39ee2ed1e5671f657646b343171274c4d0d552ac1eecb156974a715.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=8416, output_tokens=1977, finish_reason=stop, duration_ms=13125, actual_total_tokens=10393, actual_cached_tokens=8064, actual_text_counts=[8063,350,98,1,1,1,93,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 9b4636ed86614ae39ced5ae96e419af6: phase=SUCCEEDED; exact eight counts=[8063, 350, 98, 1, 1, 1, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/discuss-long-preference

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=14; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=f269342b52082de7f239f21e43cb814e1c1f9274b86b0270106d406a41504ca8.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=9140, output_tokens=1638, finish_reason=stop, duration_ms=8831, actual_total_tokens=10778, actual_cached_tokens=6144, actual_text_counts=[8063,1074,135,1,1,1,780,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 94715b9a6c8d4efba7648d3cab3dc40c: phase=SUCCEEDED; exact eight counts=[8063, 1074, 135, 1, 1, 1, 780, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/discuss-correction

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=6f8dfa29f89e93bb0ac3ca2fac57f155c3fb2bcab8f52970d49f712146a284ba.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=8431, output_tokens=2321, finish_reason=stop, duration_ms=13402, actual_total_tokens=10752, actual_cached_tokens=8320, actual_text_counts=[8063,365,113,1,1,1,93,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 140d545dd6bd46f68f1482813037bbf0: phase=SUCCEEDED; exact eight counts=[8063, 365, 113, 1, 1, 1, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/discuss-decline

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=173bce4538640616c1bdaea022bd587823da6c0849892b022dc7e77ad5e25746.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=8542, output_tokens=1928, finish_reason=stop, duration_ms=11631, actual_total_tokens=10470, actual_cached_tokens=8064, actual_text_counts=[8063,476,94,1,1,1,178,180]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 7f9d5d90c78d4b4090fa70cc104eda63: phase=SUCCEEDED; exact eight counts=[8063, 476, 94, 1, 1, 1, 178, 180]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/document-generate

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=342b4cf2a2b9b49c9dc71dbd3bd18f47531af76ab73f50cf0dfbb2f7835905f4.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=4965, output_tokens=1429, finish_reason=stop, duration_ms=9209, actual_total_tokens=6394, actual_cached_tokens=4480, actual_text_counts=[4434,528,139,140,1,1,93,135]; primary=APPLIED; progress=APPLIED.

Count audit 505146ea87784a8795e3b5f689a104f6: phase=SUCCEEDED; exact eight counts=[4434, 528, 139, 140, 1, 1, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/document-local-revise

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=5fbe6db8ea044acf8e1753fe4211defe15c559fd027f011ed7a6720c35d0c17a.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=5423, output_tokens=394, finish_reason=stop, duration_ms=3400, actual_total_tokens=5817, actual_cached_tokens=4096, actual_text_counts=[4441,979,127,140,437,32,93,135]; primary=APPLIED; progress=APPLIED.

Count audit 58f8ab58eb334c8fbde2b30afcdd63cd: phase=SUCCEEDED; exact eight counts=[4441, 979, 127, 140, 437, 32, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/document-long-specification

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=460db58c4b14f50fd02eab7eeeb4890f3d6b4610793e178f6f3d230eb37527f3.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=FAILED, validation_status=NOT_STARTED, input_tokens=30119, output_tokens=8192, finish_reason=length, duration_ms=42677, actual_total_tokens=38311, actual_cached_tokens=24960, actual_text_counts=[4434,25682,4874,20559,1,1,93,135]; primary=NOT_APPLIED; progress=NOT_REQUESTED.

Count audit 02c86adf4b464c89a2d51e73b66911cc: phase=SUCCEEDED; exact eight counts=[4434, 25682, 4874, 20559, 1, 1, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/proposals-table-row

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a128dfabaf94da66d7590d498b6a00f92e487d165ba43860a7d322c171aa1cfe.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=6264, output_tokens=963, finish_reason=stop, duration_ms=6086, actual_total_tokens=7227, actual_cached_tokens=5504, actual_text_counts=[5549,712,142,1,265,59,93,135]; primary=APPLIED; progress=APPLIED.

Count audit 29165332fa9344888823cb80222f706f: phase=SUCCEEDED; exact eight counts=[5549, 712, 142, 1, 265, 59, 93, 135]; failure_reason=None; http_status=None.

Program postcondition: PASSED: normal ACCEPTED row completion; result=BATCH_APPLIED.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/proposals-user-edit

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a128dfabaf94da66d7590d498b6a00f92e487d165ba43860a7d322c171aa1cfe.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=6264, output_tokens=967, finish_reason=stop, duration_ms=6357, actual_total_tokens=7231, actual_cached_tokens=6144, actual_text_counts=[5549,712,142,1,265,59,93,135]; primary=APPLIED; progress=APPLIED.

Count audit 3b8e7a32eb14494f83b3cb829f1fe467: phase=SUCCEEDED; exact eight counts=[5549, 712, 142, 1, 265, 59, 93, 135]; failure_reason=None; http_status=None.

Program postcondition: PASSED: normal EDITED row completion; result=BATCH_APPLIED.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/proposals-stale-original

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a128dfabaf94da66d7590d498b6a00f92e487d165ba43860a7d322c171aa1cfe.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=6264, output_tokens=421, finish_reason=stop, duration_ms=3687, actual_total_tokens=6685, actual_cached_tokens=6144, actual_text_counts=[5549,712,142,1,265,59,93,135]; primary=APPLIED; progress=NOT_REQUESTED.

Count audit 418cd8cfc25047c5be4a5ed2437fda2d: phase=SUCCEEDED; exact eight counts=[5549, 712, 142, 1, 265, 59, 93, 135]; failure_reason=None; http_status=None.

Program postcondition: PASSED: isolated stale-original injection; result=TARGET_STALE.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/analysis-local-impact

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=c243707cc9294acd0904c4d97a17aed93d1414421aaa8f78e23e0b67599a8e5d.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=4973, output_tokens=1795, finish_reason=stop, duration_ms=11835, actual_total_tokens=6768, actual_cached_tokens=4096, actual_text_counts=[4138,832,125,1,430,31,93,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit 40513e5b972542a89a28667d10e729ab: phase=SUCCEEDED; exact eight counts=[4138, 832, 125, 1, 430, 31, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/analysis-old-new

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FINISHED; count batches=1; Chat=1; status=COMPLETED; error=None; user SHA256=a3293f1c269697e7fd602f1bdca22a8700ac48d7cdf26de993f1da00f4a0f91d.

LLMUse summary: id=1, call_status=SUCCEEDED, parse_status=SUCCEEDED, validation_status=SUCCEEDED, input_tokens=5367, output_tokens=1834, finish_reason=stop, duration_ms=11884, actual_total_tokens=7201, actual_cached_tokens=4096, actual_text_counts=[4124,1240,106,1,857,31,93,135]; primary=NOT_REQUESTED; progress=APPLIED.

Count audit e371d9f61f64444390fb1b5946c7586b: phase=SUCCEEDED; exact eight counts=[4124, 1240, 106, 1, 857, 31, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

## laboratory/analysis-required-over-budget

Slot claimed; unknown/interrupted outcome must not be repeated.

Actual run=1; result=AI_FAILED; count batches=2; Chat=0; status=FAILED; error=CONTEXT_LIMIT_EXCEEDED; user SHA256=5f9afa8c56db8536de2c8e3cb724317378d1a48438f3a0493d2262b848b4c721.

LLMUse summary: none; primary=None; progress=None.

Count audit b125a789263f45d196515c81356f353b: phase=SUCCEEDED; exact eight counts=[4138, 153760, 134, 1, 153377, 1, 93, 135]; failure_reason=None; http_status=None.

Count audit d8a54ebfdd674890b7343b3025d3ae2e: phase=SUCCEEDED; exact eight counts=[4138, 153788, 134, 1, 153377, 31, 93, 135]; failure_reason=None; http_status=None.

Semantic criteria: PENDING HUMAN REVIEW against formal BE8.3; no automatic EV pass.

Actual aggregate counts=28; Chat=24. No retries.
