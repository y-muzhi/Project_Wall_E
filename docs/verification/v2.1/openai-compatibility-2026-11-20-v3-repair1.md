# OpenAI单次技术观察

状态：PREPARING。仅合成样本，最多1模型请求/2必要整请求计数，0重试；不使用真实用户数据，不切服务。

Transport: http://127.0.0.1:7897

Release-SHA256: 0561b4fd08fed60d80378d9231f1fe84f078cd129b91f1872a9faa109954f014
Profile-SHA256: 435677eaccadab44180c852a2e1fdfac5b0ec390bfdddbc17b78e3c72ab867cf
Input-SHA256: 8f57298dfd37bc85cbb759b0e1a7eb3869865edce8ee6307b4eef09b607fcaf5

COUNT_INTENT b80113ad138dea2eb982cee3aad9994caadc2a8684faec7025a2e2490f660ad1

MODEL_INTENT b80113ad138dea2eb982cee3aad9994caadc2a8684faec7025a2e2490f660ad1

结果：TECHNICAL_COMPATIBLE；输入=23108；输出=416；同release技术状态=LIVE_VERIFIED。不代表完整效果验收，未更新正常服务。

实际计数尝试=1；实际模型尝试=1；SDK请求SHA=b80113ad138dea2eb982cee3aad9994caadc2a8684faec7025a2e2490f660ad1；正常数据库及计数审计保留在本槽。

最终：[已通过并启用2.1本地OpenAI](openai-enabled-2026-11-20.md)。第三轮合计2计数/1模型/0重试，余1计数未用，不再补发；旧失败保持。
