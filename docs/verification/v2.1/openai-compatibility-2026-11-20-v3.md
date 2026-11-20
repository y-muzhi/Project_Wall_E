# OpenAI单次技术观察

状态：PREPARING。仅合成样本，最多1模型请求/3必要整请求计数，0重试；不使用真实用户数据，不切服务。

Transport: http://127.0.0.1:7897

Release-SHA256: 32999ee29f7253d93104e42801d0c55e98d4ca13815e6d9ebe2be2bd872a1df7
Profile-SHA256: 435677eaccadab44180c852a2e1fdfac5b0ec390bfdddbc17b78e3c72ab867cf
Input-SHA256: 8f57298dfd37bc85cbb759b0e1a7eb3869865edce8ee6307b4eef09b607fcaf5

COUNT_INTENT 6ca5478e15c64f896f0fd113d060db601eefb7ce2921f019018616e73f3f2a04

结果：NOT_PASSED；不得重跑该槽/自动补发，保留正常审计核对。

实际计数尝试=1；实际模型尝试=0；SDK请求SHA=None；正常数据库及计数审计保留在本槽。

## 第三轮首段诊断及修复

本段已结束1计数/0模型/0重试，400 invalid_json_schema，parameter=text.format.schema，供应方只给通用无效说明。第三轮合计上限3计数/1模型，当前剩余2/1。实际发送Schema通用元校验通过，但空白ASSESS.document_refs投影为array/enum=[[]]、无items；已修为精确空数组items string/minItems0/maxItems0，其他复合const/enum拒绝，新投影v2。不将通用元校验当接口语法兼容证明。

新openai-v2 manifest3b10a730eb5fcd346cec68b163bc4a2ee9ef1023674e513a369616bedaeaa543/release0561b4fd08fed60d80378d9231f1fe84f078cd129b91f1872a9faa109954f014，旧资源和历史v1投影保留。固定SQLite/quality_python专项schema_v2/primitives/writes/service CLI：24 passed、89.29秒、cleanupTrue；旧实际count request canonical SHA完整一致，新生成/修订原路径通过。改动F/I/B/595 app格式/diff通过。

下一段使用全新compat-04、v3-repair1.md，--count-limit=2；属于已明确授权的参数修复后剩余次数复验，不自动重跑compat-03。成功后既有切换授权保留。未知/非明确参数错误停止。

最终：[已通过并启用2.1本地OpenAI](openai-enabled-2026-11-20.md)。第三轮合计2计数/1模型/0重试，余1计数未用，不再补发；旧失败保持。
