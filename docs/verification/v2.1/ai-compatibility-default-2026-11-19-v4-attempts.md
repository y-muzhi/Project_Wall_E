# V2.1 EV60实际尝试登记

状态：已登记本次实际尝试；未运行及失败仍计入60分母。人工评价尚未执行。
Manifest-SHA256: ae62fd4ade0e1c16e500b4fe7709acb5856cc4f3ce0f4619466e5df40b53515a
Cohort-SHA256: aa3940680468b36c195e5f110bf1f66c1e0c3db864c2630053fead0d23e8d346
Profile: deepseek-v2
Release-SHA256: ecc667d6b3a61af5db4ef27b8d93b4eb3ecbba95772c0c1b3eb83f3aaaa629c3

每个固定样本最多1次Chat，无自动重试。NOT_RUN不是失败或成功；已执行的拒绝/失败计入60分母，不替换样本。真实计数批次沿冻结候选顺序，最多3批；实际Request SHA必须匹配本样本冻结候选，不能在失败后修改请求再标同一尝试。未知供应方usage填UNKNOWN，未执行填—；Counted input为真实发送前计数(含预留)，禁止按字符估算。Evidence提供真实Run/LLMUse/计数/结果的批准Markdown引用，不粘贴原始JSON或凭据。

| Sample | Status | Chat attempts | Count batches | Counted input | Usage input | Usage output | Request SHA256 | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EV21-BLANK-01-DISCUSS | STRUCTURED_REJECTED | 1 | 1 | 25866 | 26483 | 1353 | 9577c83bf2b32ab0c905929689b318637a8640b88335be760bb4619000428d4f | [ai-compatibility-default-2026-11-19-v4.md](ai-compatibility-default-2026-11-19-v4.md) |
| EV21-BLANK-01-WRITE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-01-PATH | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-01-ASSOCIATE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-01-ASSESS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-02-DISCUSS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-02-WRITE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-02-PATH | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-02-ASSOCIATE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-02-ASSESS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-03-DISCUSS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-03-WRITE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-03-PATH | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-03-ASSOCIATE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-03-ASSESS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-04-DISCUSS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-04-WRITE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-04-PATH | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-04-ASSOCIATE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-04-ASSESS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-05-DISCUSS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-05-WRITE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-05-PATH | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-05-ASSOCIATE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-05-ASSESS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-06-DISCUSS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-06-WRITE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-06-PATH | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-06-ASSOCIATE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-BLANK-06-ASSESS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-01-DISCUSS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-01-WRITE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-01-PATH | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-01-ASSOCIATE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-01-ASSESS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-02-DISCUSS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-02-WRITE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-02-PATH | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-02-ASSOCIATE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-02-ASSESS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-03-DISCUSS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-03-WRITE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-03-PATH | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-03-ASSOCIATE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-03-ASSESS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-04-DISCUSS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-04-WRITE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-04-PATH | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-04-ASSOCIATE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-04-ASSESS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-05-DISCUSS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-05-WRITE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-05-PATH | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-05-ASSOCIATE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-05-ASSESS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-06-DISCUSS | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-06-WRITE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-06-PATH | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-06-ASSOCIATE | NOT_RUN | 0 | 0 | — | — | — | — | — |
| EV21-FBASE-06-ASSESS | NOT_RUN | 0 | 0 | — | — | — | — | — |

判据与阈值见固定输入清单及后端8.3；该文档自身不会授予LIVE准入。
