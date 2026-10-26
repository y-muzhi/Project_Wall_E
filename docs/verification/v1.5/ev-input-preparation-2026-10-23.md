# V1.5 EV fixed input preparation

2026-10-23. Command: `prepare-v15-evaluation.py`; fresh temporary SQLite, normal create/edit/discussion/accept/cancel commands, compile only. No credential, admission override, Tokenization, Chat or service. Temporary databases removed. This verifies inputs and scope, not provider counts or semantic EV results.

Release: d7f67c022e1276b21b2628e93f2de76c467ba5caacdb59ac35dc99b2807b4872; source SHA256: 055cb84382012988795b3ee283d27e68526ea9baa28455639f967f9664ec6a8c

| Domain | Case | Actual user UTF-8 bytes | User SHA256 |
| --- | --- | --- | --- |
| movie | discuss-initial | 1229 | 9e398845e838ade854da4ebf859a55da66d3cd6aa483c873bd8e449c70481019 |
| movie | discuss-long-preference | 3651 | d5154916fd0d4ecb6445a6976efad2cab5a4746f68cf05f945e3ba45789d2043 |
| movie | discuss-correction | 1320 | d4be3213d876f43fa7aee6bfbdccdb3486fd55e00ee1b1ff83095ed5c88239a5 |
| movie | discuss-decline | 1679 | 154f38e10fde4b5f389670e01108bdfd889a3f391f205b19d49d3d1c67c91386 |
| movie | document-generate | 1891 | 33b02a8145ae27dcccbcd2591b92510007c53111eb4ed50b327d569d604945cc |
| movie | document-local-revise | 3290 | 222b060b1b2eafef07c77f2ee56213db71f10d737e11e9a16064ea5cecf02fc7 |
| movie | document-long-specification | 92861 | ab62a652bc881f636c884777e097937c26d210be3bc2191a6b19451eb6998dd1 |
| movie | proposals-table-row | 2353 | 3d7a4269e43b50b77d850758f621fe5a9039887c1acaf26d44126f556ecca814 |
| movie | proposals-user-edit | 2353 | 3d7a4269e43b50b77d850758f621fe5a9039887c1acaf26d44126f556ecca814 |
| movie | proposals-stale-original | 2353 | 3d7a4269e43b50b77d850758f621fe5a9039887c1acaf26d44126f556ecca814 |
| movie | analysis-local-impact | 2764 | eb94225ee58e68cd3a2f355fa2ee2df93840c9c1e0f4b00fcdf7a0a1cb99681e |
| movie | analysis-old-new | 4000 | abad11b66a780e4a22c5a87016610a37cef655f76ff6725c6bed80cb112700cf |
| movie | analysis-required-over-budget | 530035 | b692bbacc1ff6504c6481fe89413dc1834e0cc0d8e72eb0fe9f10ef61393a968 |
| laboratory | discuss-initial | 1238 | a830d72ab39ee2ed1e5671f657646b343171274c4d0d552ac1eecb156974a715 |
| laboratory | discuss-long-preference | 3690 | f269342b52082de7f239f21e43cb814e1c1f9274b86b0270106d406a41504ca8 |
| laboratory | discuss-correction | 1335 | 6f8dfa29f89e93bb0ac3ca2fac57f155c3fb2bcab8f52970d49f712146a284ba |
| laboratory | discuss-decline | 1688 | 173bce4538640616c1bdaea022bd587823da6c0849892b022dc7e77ad5e25746 |
| laboratory | document-generate | 1930 | 342b4cf2a2b9b49c9dc71dbd3bd18f47531af76ab73f50cf0dfbb2f7835905f4 |
| laboratory | document-local-revise | 3311 | 5fbe6db8ea044acf8e1753fe4211defe15c559fd027f011ed7a6720c35d0c17a |
| laboratory | document-long-specification | 92870 | 65c659cb2e83fcab603b6b93697d29e1bb535b80084b2c1a09f900ee2143f381 |
| laboratory | proposals-table-row | 2365 | a128dfabaf94da66d7590d498b6a00f92e487d165ba43860a7d322c171aa1cfe |
| laboratory | proposals-user-edit | 2365 | a128dfabaf94da66d7590d498b6a00f92e487d165ba43860a7d322c171aa1cfe |
| laboratory | proposals-stale-original | 2365 | a128dfabaf94da66d7590d498b6a00f92e487d165ba43860a7d322c171aa1cfe |
| laboratory | analysis-local-impact | 2782 | c243707cc9294acd0904c4d97a17aed93d1414421aaa8f78e23e0b67599a8e5d |
| laboratory | analysis-old-new | 4030 | a3293f1c269697e7fd602f1bdca22a8700ac48d7cdf26de993f1da00f4a0f91d |
| laboratory | analysis-required-over-budget | 530044 | 56fa2a4ba9a34356f83060a4864482fe189c17e16b1f7657622490844c4816b9 |
