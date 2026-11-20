# V2.1 EV60实际尝试登记

状态：已登记本次实际尝试；未运行及失败仍计入60分母。人工评价尚未执行。
Manifest-SHA256: 4370628898546323bb98f8002fe5f5af94cbd1943bdccba6aeb051576aa92212
Cohort-SHA256: dc9c679e3732a713b369a67649d2f6bc05c1f6d93e248bb298683873e77d2b0f
Profile: deepseek-v2
Release-SHA256: b49fd3a297e24ca950dab269769b9189b140914f8a17c031ed8a5ab1755cb5d0

每个固定样本最多1次Chat，无自动重试。NOT_RUN不是失败或成功；已执行的拒绝/失败计入60分母，不替换样本。真实计数批次沿冻结候选顺序，最多3批；实际Request SHA必须匹配本样本冻结候选，不能在失败后修改请求再标同一尝试。未知供应方usage填UNKNOWN，未执行填—；Counted input为真实发送前计数(含预留)，禁止按字符估算。Evidence提供真实Run/LLMUse/计数/结果的批准Markdown引用，不粘贴原始JSON或凭据。

| Sample | Status | Chat attempts | Count batches | Counted input | Usage input | Usage output | Request SHA256 | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EV21-BLANK-01-DISCUSS | LIVE_RETURNED | 1 | 1 | 16638 | 15617 | 738 | ffdf0cb0c99d3aec1128ba1a53b6d6a7634dc860ac1a3ced64001339c6f96d80 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-01-WRITE | LIVE_RETURNED | 1 | 1 | 16680 | 15659 | 1287 | 97eb5883f9eac74de39cd173c2989162b416754f52d732e6e86edb6a3aafd1c8 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-01-PATH | STRUCTURED_REJECTED | 1 | 1 | 16691 | 15670 | 1277 | 7a786925aabab7fc7a964970138e3af71fac555c8f57fc93126b7727f677691c | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-01-ASSOCIATE | STRUCTURED_REJECTED | 1 | 1 | 16797 | 15776 | 1246 | bc76b8731acc0b67b1f98eb720dd6c957e29e37e27958516d72b3ece22f6cb44 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-01-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 16662 | 15641 | 1147 | baec8b2e240725bb4fd0c7f56fcb226b3e67f50532853cc7db22baa4cbdfabc9 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-02-DISCUSS | LIVE_RETURNED | 1 | 1 | 16638 | 15617 | 816 | 4b3c7edef8a963b8805397f2c715a34fd4b3405adc13b540b01bbb4f5a1c4653 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-02-WRITE | LIVE_RETURNED | 1 | 1 | 16680 | 15659 | 1457 | 7b5935c52928b10d8edeb537dceee122a24c67341082e1a79e02ba3a45b95655 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-02-PATH | LIVE_RETURNED | 1 | 1 | 16691 | 15670 | 1543 | 00500c2e85b2e61069992a5d5231f9691b3c546bdb2b706e736c381a92bd685a | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-02-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 16762 | 15741 | 709 | 239efe0989ea4287981f9362aa4a3227c7ddc98f5047c129bbc18470ed05815d | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-02-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 16662 | 15641 | 1610 | 16c4618714cfff21bde571aeca5cb40bf60a6af7e86fc3ab41f2497c3d961b6b | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-03-DISCUSS | LIVE_RETURNED | 1 | 1 | 16756 | 15735 | 744 | 26a779697bd967a9326d13e394358bf19be732c1bec31572ff94212188274871 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-03-WRITE | LIVE_RETURNED | 1 | 1 | 16798 | 15777 | 1460 | d76ba02e39d8f4768c5698c23688b8cd3b9c4c10e21691339013c358879f24cc | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-03-PATH | STRUCTURED_REJECTED | 1 | 1 | 16809 | 15788 | 1445 | b28a311f4c7330d537eb950282db6f4ea2fc5e218fd5faded79429e9bb321601 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-03-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 16915 | 15894 | 761 | 889edd9bc79bb2888d1d545266490f09c4f37a10600e4edc5fd48e8e383c4dbb | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-03-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 16780 | 15759 | 1011 | 655ff0caef3293d6e0e6751302e94fddbe524fab8ddf7e2e1a6e12809cdaa7d4 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-04-DISCUSS | LIVE_RETURNED | 1 | 1 | 16636 | 15615 | 799 | 522dcd205ac6d0e379f4c4579797997c432f2f8923c455ac2ee346916c8652fb | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-04-WRITE | LIVE_RETURNED | 1 | 1 | 16678 | 15657 | 1421 | ff9d0b15bc36292536a47e805efb2fe3a02f93ee9edd76631b5f3ee02fa86a25 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-04-PATH | STRUCTURED_REJECTED | 1 | 1 | 16689 | 15668 | 1071 | 47dfc5f64a31c4fa5fd1f3e898ac7d238d75563d67856ab2825d46138097e20d | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-04-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 16760 | 15739 | 788 | 4329bdf6f64cedc8633c4a201e40ab3ec480116eca3cdfe01d75c1bf75c28081 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-04-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 16660 | 15639 | 1115 | 830e1e20c0a93001f8d4b8be6cb99ba8648ec486766564a34c7ecea8c82793c4 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-05-DISCUSS | LIVE_RETURNED | 1 | 1 | 16642 | 15621 | 845 | be288a4be651668ee4b438366511d1d153d655b54c0921358f9e7735b2a868c5 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-05-WRITE | LIVE_RETURNED | 1 | 1 | 16684 | 15663 | 1183 | c8c89f3082d861e01013ebb9272c5e116e793a06c2519eac15f6f50ab97132bf | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-05-PATH | LIVE_RETURNED | 1 | 1 | 16695 | 15674 | 1217 | 78126625dd1cb230be0b8f397f9ac4443ceaed03a86da39d09c7c6dd90d264e3 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-05-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 16801 | 15780 | 659 | 77967480185d4124b02edbdf50377aa46f78d2b103bf6c735c01c5640bcc8bfa | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-05-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 16666 | 15645 | 1082 | a4cdc9cc08be5ddecf9c962155c97b984ede9dd9629d0b33bb994814e36ea1da | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-06-DISCUSS | LIVE_RETURNED | 1 | 1 | 16722 | 15701 | 838 | d2aba036b7c38db6dc1e747bd53f169abd06b9b09e895a8694dc380fbaacd42e | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-06-WRITE | LIVE_RETURNED | 1 | 1 | 16764 | 15743 | 1033 | da69ef031de01bc1bb472054737c5940db706dcbd001b44af0608d2bfffc5d50 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-06-PATH | LIVE_RETURNED | 1 | 1 | 16775 | 15754 | 1574 | 7099f9d3891106e41cfd84b0f6e582b5199fd9280ff5c57182c6f2c524beaa9b | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-06-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 16757 | 15736 | 663 | f78015244e27965869cd340eee872f739fffda35380d4a42a68243b8359d702d | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-BLANK-06-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 16781 | 15760 | 1026 | 6ae80f5dfe4c74a1776d65e60fdbd54a9d0e41705a74cafbdce5202d97847f8a | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-01-DISCUSS | LIVE_RETURNED | 1 | 1 | 16813 | 15792 | 677 | bd615dff41fb9b1a6b43000e7bf62ab93b91a1ce612714a2a2fbbe03e32f80ae | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-01-WRITE | LIVE_RETURNED | 1 | 1 | 16855 | 15834 | 1073 | cdbba01349eb2afd2c988c45b5bab81e5c7501f278ce25e7adc5625922b1eba9 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-01-PATH | LIVE_RETURNED | 1 | 1 | 16866 | 15845 | 1294 | 50c6117a73ebed470e3524a3f81ce493989264bc55f7591d0bb1bffb542b943c | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-01-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 16891 | 15870 | 1274 | 7385e61e3c8dfa75c2e8c32e506eb8a66abddd6625a042dfe8c29f86bf40fd10 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-01-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 16837 | 15816 | 1075 | 4868e6f9c0f1d1c0bfe53bae5caab4c53fa4eeca9bad800c66aa31949485807c | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-02-DISCUSS | LIVE_RETURNED | 1 | 1 | 16813 | 15792 | 589 | c0ac08458d195363a54917de4a559fa756478a50033b54890d931bfa3b67adf5 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-02-WRITE | LIVE_RETURNED | 1 | 1 | 16855 | 15834 | 1104 | 7ff3edcd4c3dbd3ed2ae396ba0f1953f5efc0a58c69371b705d0a78a6dd1e13f | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-02-PATH | STRUCTURED_REJECTED | 1 | 1 | 16866 | 15845 | 1436 | 505b76e63a20d8d5c99b1985bf7f6355cdc678079b842ddbd6c82b8b61a00b07 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-02-ASSOCIATE | STRUCTURED_REJECTED | 1 | 1 | 16856 | 15835 | 1134 | b54e11443c18dba49d6e2cae399a698d5288b542d30322ab063178dc4acc0781 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-02-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 16837 | 15816 | 1045 | d345cb0ee30f52d0cdddbdadaea6db2f1c469d1be8ee6a5201703d97eb7861a0 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-03-DISCUSS | LIVE_RETURNED | 1 | 1 | 16931 | 15910 | 691 | e407b1d6b11154e97ff84b8f413b5d0a550bcdbac51a8b3f608965b728c5c2d2 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-03-WRITE | STRUCTURED_REJECTED | 1 | 1 | 16973 | 15952 | 1101 | 5a5e44d8dc0417601e4aa913227e769df2f3af879ced958106632dff236469f8 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-03-PATH | STRUCTURED_REJECTED | 1 | 1 | 16984 | 15963 | 1358 | b147ac9de6d21ed6710a2d5690ca9c33b66f5613f52fe0a696f40e431927293c | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-03-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 17009 | 15988 | 1108 | d90ea45ee63a4e3f91a2ba561e4cfd07d5e0a70d5abcf28d076652aca6e1408f | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-03-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 16955 | 15934 | 1792 | 5a9250df2613bacd0780fe732d9c0861668788266cdf2c13641ea1e872631a40 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-04-DISCUSS | LIVE_RETURNED | 1 | 1 | 16811 | 15790 | 949 | bf821c389fd35612765ce12d970576abe57e1886d2d9bf2bc26b9311f87a7e4f | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-04-WRITE | LIVE_RETURNED | 1 | 1 | 16853 | 15832 | 1042 | 7e82dd0532bf49285e549a3249c327561ec23c31a0f6dd182b71f15ca5467d1f | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-04-PATH | STRUCTURED_REJECTED | 1 | 1 | 16864 | 15843 | 1050 | 07a26c83480a188d170cee6210671caf8451cd06e1bd85f2f879587df88d0bbd | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-04-ASSOCIATE | STRUCTURED_REJECTED | 1 | 1 | 16854 | 15833 | 1225 | 69c717b70d303a6d15e3db43a72bf40ce723e20f6fe9dac1baa7c78140499fe3 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-04-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 16835 | 15814 | 1066 | 72e1f3ab47b26dea68f7fa48460e3cbf078b2436d921cb9befeaabaa28114be5 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-05-DISCUSS | LIVE_RETURNED | 1 | 1 | 16817 | 15796 | 853 | 80611eb976c4b23663be677722f3e136ac43e1bdbd6f45c5c5d898dcf56aca8d | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-05-WRITE | LIVE_RETURNED | 1 | 1 | 16859 | 15838 | 1067 | acc637edde2f652cd8a0b6c9668477bd2d8197a1879deb17f3a13f666e4ab9a6 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-05-PATH | STRUCTURED_REJECTED | 1 | 1 | 16870 | 15849 | 1132 | f46a0428745817a2eccadc1fe4a202c7895f58fc40d400cc847c6e39a2419325 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-05-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 16895 | 15874 | 723 | 3724fa1786661768c39f802f03cd847bd31ea08857633ba3428614a3cb147403 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-05-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 16841 | 15820 | 1913 | 7dcf6c1890eb77a508c9320f57f4ccded30a08226a26933cc1de6b96c2a34e05 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-06-DISCUSS | LIVE_RETURNED | 1 | 1 | 16816 | 15795 | 890 | 4c58a8fc72f83d95bc91017a0d74b46fc16450ec9dae2b0865b9f51c548d88ca | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-06-WRITE | LIVE_RETURNED | 1 | 1 | 16858 | 15837 | 920 | 7d35ea83f4d31d70b75c97cb94d4dced562e9ca7ea4cf6488e17faaf57108e42 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-06-PATH | LIVE_RETURNED | 1 | 1 | 16869 | 15848 | 1262 | 9aa700a45dd448eec6a21bee08ea20c54a628d883e844692119b16291998c0b1 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-06-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 16851 | 15830 | 736 | 5cb39d1381723c334b226430eac337a2da87ad58fdea7b70f4897e75575c7ef9 | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |
| EV21-FBASE-06-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 16875 | 15854 | 1251 | d05b451dcc6eeeb87ff6ca4e3dd36a11255ba54d580aacf474f052389b7d4a0b | [ai-admission-default-2026-11-18-v2.md](ai-admission-default-2026-11-18-v2.md) |

判据与阈值见固定输入清单及后端8.3；该文档自身不会授予LIVE准入。
