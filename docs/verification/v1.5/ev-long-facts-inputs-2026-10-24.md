# V1.5 EV fixed input preparation

2026-10-24 (Asia/Hong_Kong). Command: `prepare-v15-evaluation.py`; fresh temporary SQLite, normal create/edit/discussion/accept/cancel commands, compile only. No credential, admission override, Tokenization, Chat or service. Temporary databases removed. This verifies inputs and scope, not provider counts or semantic EV results.

Release: eeb7925e52dbecb521ad19a448ba7ae24be4aac63ff8d5b4a0a384ba534c4a68; source SHA256: a6b92ffe1975035afbc2ba171c24ee4127bd1e96cdda82675c5d003b10b28a6d

Aggregate text-byte capacity is checked separately from exact token counts. Required-input fixture now has 4000 deterministic lines; its token-limit result is unverified. Original 8000-line generator remains byte-identical in docs/sources/v1.5/prepare-v15-evaluation-v12-frozen.py.

| Domain | Case | Actual user UTF-8 bytes | User SHA256 | Eight-text UTF-8 bytes |
| --- | --- | --- | --- | --- |
| movie | document-long-specification | 107508 | 4a618a2f76a01cdcf1c41ea030dc05d12d8e37019e6d31d28144f5f3ccd4ed24 | 230401 |
| laboratory | document-long-specification | 108558 | 460db58c4b14f50fd02eab7eeeb4890f3d6b4610793e178f6f3d230eb37527f3 | 232501 |
