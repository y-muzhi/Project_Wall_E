# V1.5 v14单次技术观测

2026-10-24，Asia/Hong_Kong。当前用户独立授权，最多1计数／1Chat，完整131072／8192／139264预算，零重试。新槽data/v15-observation-20261024-v14-once，未知先读原槽不重发；后续26EV须技术LIVE及首轮结构通过。

release=ac9c887f0dc52482d7cc329a0faaeb2cfd2e3f69c8e6f89df90f5d16b7a21d14；profile=61941797052baa3c4a6cc1df54759b91d7fa933d2a4b98ec19d8b3b116cfc70e；observe工具SHA256=5c5a5dadc34bda4b8b89a45ef1fc0f671db89982d64d17130d1928a13ddd251f。固定源码、输入及完整权限见v14-batch-authorization-2026-10-24.md。尚未填实际结果。

实际CLI退出0，正常审计只读核对：

- id=1
- call_status=SUCCEEDED
- parse_status=SUCCEEDED
- validation_status=SUCCEEDED
- input_tokens=8287
- output_tokens=1965
- finish_reason=stop
- duration_ms=14567
- actual_total=10252
- cache=0
- gap=3
- admission=LIVE_VERIFIED
- application_result=NOT_REQUESTED
- progress_result=APPLIED
- root=IDLE
- documents=0
- gate_passed=True

实际1计数／1Chat，零重试；原正常证据保留，不写用户库。此技术结构门通过，允许本次授权进入26EV。
