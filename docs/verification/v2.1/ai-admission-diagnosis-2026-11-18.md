# V2.1首轮真实结果只读定位

日期：2026-11-18。本报告在唯一默认组执行期间建立，实际分母、次数和完成状态以ai-admission-default-2026-11-18.md及其attempts为准。没有重发、修复/替换模型返回或改写样本，没有修改本轮正在使用的代码/资源/固定清单。

## 已复核事实

- EV21-BLANK-01-ASSESS及EV21-BLANK-02-DISCUSS：正常供应方返回及严格OutputDiscussion Schema均通过；进度纯校验apply_progress抛出ProgressInvalid：Next step names an unavailable topic。正常C07已拒绝整个结构单元。不能因为可读message正常就称进展已保存。
- EV21-BLANK-02-PATH：严格Schema通过，prepare_publication的result_routes校验拒绝，字段错误为“必须逐项明确被取消步骤的全部原成果去向”。这是成果承接遗漏被实际门禁拦截，不是凭据/模板文件丢失。
- EV21-BLANK-01-WRITE虽然标为LIVE_RETURNED（仅程序校验通过），实际cards.purpose为CLARIFICATION，没有按该派生任务输出STAGED_WRITE。不能把程序接受率当任务可用率。
- EV21-BLANK-01-PATH严格结构及程序接受，但返回cards=null，可读message明确优先执行原输入“只解释…不改路线”，拒绝派生任务的拆步要求。固定输入中同时包含不同方向的基元及派生任务；需要评审指令优先级是否明确，不能事后改本轮冻结输入而沿用同一结果。

## 定位方法与边界

只读打开本轮隔离Schema210正常DB；固定SQLite在sqlite3导入前activate。读取原调用snapshot/parsed output，使用原catalog/profile恢复已计数context。复核严格Schema，并在只读transaction内运行apply_progress、prepare_model及prepare_publication的纯准备路径；不运行C07保存、数据命令、模型或计数。

只读重验使用失败记录当前尚未应用结构的状态，不能推断所有成功样本或所有历史时刻。上述结果未改写原始normal audit。错误的可读原因是定位线索，不替代两名实际独立人工评审。

## 发布边界

当前已出现设计8.3的严格协议/依据及成果承接阻断，不能用首个技术观察已产生的LIVE_VERIFIED直接启用正式用户AI，也不伪造人工评价。先保留完整本组分母与真实结果；若后续调整Prompt、输入配方或release，应新增资源/冻结记录并重新明确新轮调用授权，不能修改v27或本轮清单字节、悄悄使用剩余次数换资源补发。
