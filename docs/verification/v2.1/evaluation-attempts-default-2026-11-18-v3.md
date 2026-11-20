# V2.1 EV60实际尝试登记

状态：NOT_RUN。本表没有真实调用或人工评价结果。
Manifest-SHA256: b96887c785b8d6dcb8206b558c47f1e8bf58ce4a4609faffb1f302a670542b9d
Cohort-SHA256: ae529100c79ef98f5fc6fa8c223810d9cffa1febbe4e3de6b817450ca06fd57e
Profile: deepseek-v2
Release-SHA256: a76797d1988bf81f518933ae46f571ee13c5b67db5b2de7b94cd9ba6b526bd21

每个固定样本最多1次Chat，无自动重试。NOT_RUN不是失败或成功；已执行的拒绝/失败计入60分母，不替换样本。真实计数批次沿冻结候选顺序，最多3批；实际Request SHA必须匹配本样本冻结候选，不能在失败后修改请求再标同一尝试。未知供应方usage填UNKNOWN，未执行填—；Counted input为真实发送前计数(含预留)，禁止按字符估算。Evidence提供真实Run/LLMUse/计数/结果的批准Markdown引用，不粘贴原始JSON或凭据。

| Sample | Status | Chat attempts | Count batches | Counted input | Usage input | Usage output | Request SHA256 | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EV21-BLANK-01-DISCUSS | NOT_RUN | 0 | 0 | — | — | — | — | — |
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
