# V2.1 EV60实际尝试登记

状态：已登记本次实际尝试；未运行及失败仍计入60分母。人工评价尚未执行。
Manifest-SHA256: bb5c3905eba44d4cbd4749f561b86bd1b5645336694e76addffcb37b0825bd54
Cohort-SHA256: 65571e44fc4073506b9f975b53963bae1863661f85d1adcb3a787831c5dc5fce
Profile: deepseek-v2
Release-SHA256: e5e0860a49812006f72d6f0de3f7d3c06420d87b8e7a45f683d9e50d52769bfe

每个固定样本最多1次Chat，无自动重试。NOT_RUN不是失败或成功；已执行的拒绝/失败计入60分母，不替换样本。真实计数批次沿冻结候选顺序，最多3批；实际Request SHA必须匹配本样本冻结候选，不能在失败后修改请求再标同一尝试。未知供应方usage填UNKNOWN，未执行填—；Counted input为真实发送前计数(含预留)，禁止按字符估算。Evidence提供真实Run/LLMUse/计数/结果的批准Markdown引用，不粘贴原始JSON或凭据。

| Sample | Status | Chat attempts | Count batches | Counted input | Usage input | Usage output | Request SHA256 | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EV21-BLANK-01-DISCUSS | LIVE_RETURNED | 1 | 1 | 15696 | 14675 | 730 | 7306b17a89e0bc2e45f3e13d8d1496933c45b9df9418f33d44ee8b715fd980f9 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-01-WRITE | LIVE_RETURNED | 1 | 1 | 15725 | 14704 | 1258 | 4cdb7eb79191f2c1cce8f2fb86b53b4a9c98c94ce0e6141585122c691ea61417 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-01-PATH | LIVE_RETURNED | 1 | 1 | 15726 | 14705 | 443 | 248957807f913af87201e28394609c1c0936fb5a8556cb455028c55e636f1425 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-01-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 15855 | 14834 | 1020 | 4762a8ed9fdabaa764ee1d9a28745716c0cd23918107fb58ffdbe0487a27db52 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-01-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 15720 | 14699 | 1220 | 495797199fdbe3821550483feed47fc0fe64d90ee86d09138c2f0239bc18b0cd | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-02-DISCUSS | STRUCTURED_REJECTED | 1 | 1 | 15696 | 14675 | 1678 | 2eb852d7c41858f5b0df76cea46382a3bdaf95301675000c9f3fc7cb74494a17 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-02-WRITE | LIVE_RETURNED | 1 | 1 | 15725 | 14704 | 1465 | 8e68e3295e65d7186d11acf181dc37510f5951e0267171ba36d78e04728cce5c | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-02-PATH | STRUCTURED_REJECTED | 1 | 1 | 15726 | 14705 | 1363 | 4ae39f44625773298be37aeee0af2e329bf8adb5b29713c1ec54d3d13677336e | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-02-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 15820 | 14799 | 1874 | 972103e637d3aaebe159b4a805396beaf8077f90086235cff58e7efb20e8b545 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-02-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 15720 | 14699 | 1464 | 0859a1769af8f4ec1d4a161dfeaa75f3060fb6740eddbd6364cd49f544450391 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-03-DISCUSS | LIVE_RETURNED | 1 | 1 | 15814 | 14793 | 682 | 962aa4c9c016f906ac19fd20d932f11cfd7770544b9c98ed5dfe6ebab1d004eb | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-03-WRITE | LIVE_RETURNED | 1 | 1 | 15843 | 14822 | 1604 | ab0794071471ce3280b63c6607d6f722d8421084e41e5babfcd6a2b82265b451 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-03-PATH | STRUCTURED_REJECTED | 1 | 1 | 15844 | 14823 | 1742 | fab98e76ee333cc8c77c73f3fe3c952ef7c7b9f42bfe9eb08c8ce04f132b6c14 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-03-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 15973 | 14952 | 802 | 90adff30d1fd94d66f387fd9ba200a05235415d88dcff39aa04c86ee952493b3 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-03-ASSESS | LIVE_RETURNED | 1 | 1 | 15838 | 14817 | 941 | 74c0a5ad093abca548b174f7652f21faddc03839ba9333f01d97deadf89b79fd | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-04-DISCUSS | LIVE_RETURNED | 1 | 1 | 15694 | 14673 | 921 | e737b2211da4fcb162a947200fc20f61ba1abc8d0c43631b89854357e59125dd | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-04-WRITE | LIVE_RETURNED | 1 | 1 | 15723 | 14702 | 1934 | 94497118c2d0310c73ff1e1abc6049e8bdefbc54555528ddff7244cba4f2bd1c | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-04-PATH | STRUCTURED_REJECTED | 1 | 1 | 15724 | 14703 | 1208 | f6d2ce9d42353d6d567d2831afbfb13dfa420bd08819ece92a72b6c884c72232 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-04-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 15818 | 14797 | 964 | f58574d531bcab1a7edcaa33f664c547d767a6edf703c38ad0eaaec1a36c208f | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-04-ASSESS | LIVE_RETURNED | 1 | 1 | 15718 | 14697 | 1113 | 80c8630f5a37c54e12540e22699f535cc097122a0fe1448a5d097a22dd9c92a0 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-05-DISCUSS | LIVE_RETURNED | 1 | 1 | 15700 | 14679 | 733 | 7abb9c4fec6245776cd36736942a296c4916117307938c95d03dbb74d560feb2 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-05-WRITE | LIVE_RETURNED | 1 | 1 | 15729 | 14708 | 1813 | 57a0c15cbefe613c46f14746fcafea2cd0324dcb0c08c67e0742152f81f5b2ac | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-05-PATH | STRUCTURED_REJECTED | 1 | 1 | 15730 | 14709 | 1250 | b5f99e70425d835aaa6e0fb2f7dddc5313396b2115e9a6b686e49983c9c3d175 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-05-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 15859 | 14838 | 763 | e8317446921947ff90984bb7fb886a4f0d40dd018075678ebe6079332a6b7116 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-05-ASSESS | LIVE_RETURNED | 1 | 1 | 15724 | 14703 | 1593 | 6de3f572619cea771773a499120fc12f25945a266bc75178203095b98418cfaa | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-06-DISCUSS | STRUCTURED_REJECTED | 1 | 1 | 15780 | 14759 | 829 | 007aab3a9bd1beb1ec06d771f0c578b988d331c3d92e5a13cacf4cc201255e8d | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-06-WRITE | LIVE_RETURNED | 1 | 1 | 15809 | 14788 | 1302 | 3c519b7dd862c9c74be777f7547bd16684c52630ad7c8c164db89d3e845fa14e | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-06-PATH | STRUCTURED_REJECTED | 1 | 1 | 15810 | 14789 | 1547 | f0ef23dfc8131f3d1cd6bd58611161e678509e43c26c604d9408aa3e56548ead | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-06-ASSOCIATE | STRUCTURED_REJECTED | 1 | 1 | 15815 | 14794 | 944 | 881e6eae59bcca201eeffdea643f938c3982e5abbd8436c1e5ae8ceb86402a5c | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-BLANK-06-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 15839 | 14818 | 1230 | d7bc3b3c7a54c8fea9a9c0393db8f38b247043c6bee6ccae538c631a2a10808f | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-01-DISCUSS | LIVE_RETURNED | 1 | 1 | 15871 | 14850 | 758 | 71b44b35017da51e18f6d597a1479f8a6e16a1f7047f1dbd1ba0ba3b08cc756d | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-01-WRITE | LIVE_RETURNED | 1 | 1 | 15900 | 14879 | 1181 | 01675b897ee7275b6bd2e04ee7db9e9d6984832c086fbf941411b2be303f2b49 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-01-PATH | LIVE_RETURNED | 1 | 1 | 15901 | 14880 | 681 | 8494600d5c3472577945bf288ee34c63cec885728567a278600f36547905c786 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-01-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 15949 | 14928 | 1033 | 620946a1bd52af6b207f9c81874281b13d9d43047e1180fcfecc2b9adb7ee435 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-01-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 15895 | 14874 | 1003 | 6df2598cc59d7b18d99eb6bebf8c46f746e06783b329d7d62020b5f5f1ebd736 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-02-DISCUSS | LIVE_RETURNED | 1 | 1 | 15871 | 14850 | 889 | 52a8d3d6c4dd63a5f199f2476a5c24cc0c2a8bfd0283596813c678eb996b0ae1 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-02-WRITE | STRUCTURED_REJECTED | 1 | 1 | 15900 | 14879 | 1857 | 925a580e20d20fe0a0f255629924467c3bd0b431174dd44d96c406903df7e3f5 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-02-PATH | STRUCTURED_REJECTED | 1 | 1 | 15901 | 14880 | 1778 | a8dc542bb0d2cf98c77d5e01ba36ec297119ea2b6c9f305a5967e11cf22e23a6 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-02-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 15914 | 14893 | 1917 | 20c76386f72d8df82915896091251c6a1f3f6bb15ae486624c9b50abe6dde265 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-02-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 15895 | 14874 | 1941 | a3b990918368b61282a1b29cf34a28b383d6eaea35320d5569c445b74c3b843c | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-03-DISCUSS | LIVE_RETURNED | 1 | 1 | 15989 | 14968 | 621 | d286c185905f41a06a0c42935666478f7fde42ed5e029548802cc592d96613f5 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-03-WRITE | LIVE_RETURNED | 1 | 1 | 16018 | 14997 | 1223 | 3c8f79b8329d7acefe239f32e66589f1a4bbbb2c5df33a3b7a80c30b5c90d5dd | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-03-PATH | STRUCTURED_REJECTED | 1 | 1 | 16019 | 14998 | 2067 | b68c340fe6e8d58cd6e4a85813be2a637baf560630b714170a25c670d8b9aade | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-03-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 16067 | 15046 | 1226 | bc4ead2b588ee062bb333202addc0e7f9f6b2c7c1ee0c85460ea6610f93dc224 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-03-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 16013 | 14992 | 1745 | 02616c425306fbeb12616d40cea1d377c0c83bee29bc2e167317e03356bc1233 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-04-DISCUSS | LIVE_RETURNED | 1 | 1 | 15869 | 14848 | 1216 | 3f9dce347299dfb8c4ee1e76030f24f95fbf5654443c6e049ccde0ab644a50ae | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-04-WRITE | STRUCTURED_REJECTED | 1 | 1 | 15898 | 14877 | 1733 | 38be974187179a44d2dd93865665fe25d4fad5d1014fef4b0daf3d0b674ab937 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-04-PATH | STRUCTURED_REJECTED | 1 | 1 | 15899 | 14878 | 1218 | 0d5f254dac79eb71720d15565903afb06112bbef10e7b72b62e129b20c35b605 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-04-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 15912 | 14891 | 919 | 5717d18dcede27b2940452405c9719884aba1d1929b940f886031203964dc2e0 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-04-ASSESS | LIVE_RETURNED | 1 | 1 | 15893 | 14872 | 2142 | cc3f2d64e830b382dd148344fbe3894753307408f72c048ba23c2c46e5f776b8 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-05-DISCUSS | LIVE_RETURNED | 1 | 1 | 15875 | 14854 | 1596 | 9f4d8e04eeace7ae680dac7cbfc6e424c469b211e1780ef236413bf02c13e597 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-05-WRITE | LIVE_RETURNED | 1 | 1 | 15904 | 14883 | 1241 | f133d60fd52af308bd097e484cbca84d32433bdb2b9420aa3acd726f4ca544e6 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-05-PATH | STRUCTURED_REJECTED | 1 | 1 | 15905 | 14884 | 1074 | a4d82bf0cb43ce599ffad361bd1b4a6a630b0957be78167160708f9ff7b5919a | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-05-ASSOCIATE | LIVE_RETURNED | 1 | 1 | 15953 | 14932 | 1016 | 987173c6ee545d3cd1013f83e2e681100bb157aa0c708d84ec4a8063716cbba6 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-05-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 15899 | 14878 | 2114 | d64ccc32b1a2ae5ef7927543f3f25ac1829f6bb35d5da250617c0eb0c6194a84 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-06-DISCUSS | LIVE_RETURNED | 1 | 1 | 15874 | 14853 | 745 | a7c7c28d1610f789abda5f78b2d1976939fb38cb61f874cb1d9e03451248d14d | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-06-WRITE | LIVE_RETURNED | 1 | 1 | 15903 | 14882 | 1584 | c5e4fd4fe968f3e4f6611a127dfddcfc4905d305341bb77e05da8afc43ed3a5c | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-06-PATH | STRUCTURED_REJECTED | 1 | 1 | 15904 | 14883 | 1996 | df7cdfd88909cf4370379837096b79d64968a2e5164dcf8cc4c80861c003c66f | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-06-ASSOCIATE | STRUCTURED_REJECTED | 1 | 1 | 15909 | 14888 | 1155 | e4cf9862365d7adcf64c29a2e25a2c921002c712f9e4966053db5f917e2360e4 | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |
| EV21-FBASE-06-ASSESS | STRUCTURED_REJECTED | 1 | 1 | 15933 | 14912 | 1539 | e3c29e8277e6870a1d0e0e6c2fba7034c0b519c9b9069a226d4171df941ee8fe | [ai-admission-default-2026-11-18.md](ai-admission-default-2026-11-18.md) |

判据与阈值见固定输入清单及后端8.3；该文档自身不会授予LIVE准入。
