# WALL-E V2.1模型评测离线准备迭代

状态：已实施及离线检查，真实评测未执行；目标软件V2.1；独立pending，未合入正式设计。来源：后端0.1-draft-4第4章APP-FORM-DISCUSS、第6章Canonical/Wire及第8.3节EV-FORM-AI；原设计字节不改。

## 本轮范围

用户要求按两小时工作量继续实施。先完成固定60样本的可重建实际输入、Profile/release及人工判据，再检查真实执行前的技术衔接。本轮只用合成隔离数据及离线替身，不读取真实凭据，不调用模型/计数，不授予LIVE，不更新用户库/服务，不提交推送。

配方是8.3所需的FBASE正文/路径派生，不冒充8.1所有共享场景的完整FBASE。SQL历史前置与实际创建、人工编辑、结束、C01接受分别说明；保留成功幂等回执，不为“空账本”删除不可变记录。60样本固定12×5，8例在真实结束后的s2改稿/讨论并核对Closure不变。暂缓i2保留真实用户依据及明确覆盖，未携带实体不能擅自MOVE。

## 实施前确认：隔离观察的目标文档

实际首样本C01已接受，但CollaborationObservation.check_connection仍要求run.target_document_id为空，报Only the single isolated discussion observation is permitted。V2.1实际DISCUSS冻结当前文档为target_document_id，因而既有新release技术兼容观察无法进入；不是供应方失败或已发生付费调用。

输入：已验证新formation release、固定Profile、唯一隔离数据库/单文档/单RUNNING DISCUSS及冻结授权。输出：仅返回当前私有Observation证据，调用前预算仍由原capability执行；不写LIVE、不授予正文写入权。

不变量：目标及V依据沿共享严格integer约束，明确排除布尔和浮点，不利用Python等值关系代替类型判断；旧release仍只允许原空target；新formation release仅接受target=document_id及冻结DISCUSS授权、空allowed_targets、同一当前V1空正文；其他文档、写入操作、已有正文、多文档/多Run、配置改变及预算超次继续拒绝。只修改原私有观察校验，不增加HTTP/Worker开关或第二条模型执行流程。

## 结果

最终工具15项/观察12项合计27项及13子检查通过，旧观察/长输出18项回归通过；两个既有Profile各自60样本/120候选-r2冻结并全量重建一致。实际ModelGateway MockTransport证明请求体字节顺序，首观察替身C07→Schema210源审计→另一隔离库常规C07通过，原正文和源审计保持；所有临时资料已回收。局部替身LIVE_VERIFIED不改变正式资源OFFLINE_READY。详见[验证](../../../verification/v2.1/evaluation-preparation-2026-11-17.md)和[操作说明](../../../project/v2.1/模型评测实施说明_V_2.1.md)。正式设计原字节未改，独立迭代未合并。本文件不提供任何真实调用许可。
