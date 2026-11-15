# Schema词法复用与逐事务核验（2026-11-13）

香港15:56登记[独立迭代](../../iterations/pending/v2.0/WALL-E.Schema词法复用与逐事务核验性能迭代V1_V_2.0.md)后实施。master／28a7c9e工作区继续保留其他任务改动，无提交／用户库／服务／供应方操作，源码及格式结果同目录临时文件fsync、原字节CAS及原子替换。

## 实际问题与实现

原模型回归的整组240／120／60／90秒限时曾结束运行，不作通过；有界线程输出定位实际工作在schema_inspection.sql_tokens，经真实每事务Schema核验进入，不是模型调用等待。原模型授权单组10项136.62秒完整通过，最慢准备13.48秒，说明整组时间不足与重复解析成本。仅记录这些实际观察，不把某次堆栈当全部时间的精确分摊。

schema_inspection.py保留原_scan_sql_tokens扫描算法，对完整SQL文本长度≤8192的纯函数结果以512项LRU复用，返回不可变tuple；超长和异常不驻留。inspect_schema／verify_schema的实际sqlite_schema及各PRAGMA读取／比较没有改变，不缓存数据库路径、连接、SchemaSnapshot或“通过”结论。

## 已执行检查

使用项目.venv、固定tools/python-v20.py，TemporaryDirectory及tools.quality_gate.environment()，禁外网／用户data与正常密钥，pytest不写缓存。实际命令形态：

.venv/Scripts/python.exe -B -u tools/python-v20.py tools/quality_python.py backend/tests/infrastructure/test_v20_schema_lexical_reuse.py backend/tests/infrastructure/test_v20_data_retention.py backend/tests/infrastructure/test_v20_schema_state.py backend/tests/code_tasks/test_coding_model_gateway.py backend/tests/code_tasks/test_task_model_authorization.py -q -p no:cacheprovider --tb=short --durations=3 --basetemp <本轮独占临时目录>/pytest

结果50项通过、12subtests通过，123.93秒（包装总124.37秒）。新增6项覆盖冷热字面量／运算符、重复非法SQL、长文本与有界条数、实际SQLite另一连接改变索引谓词／新增对象后拒绝，以及同名不同定义的另库拒绝。原数据保留、200来源／历史、模型网关12和授权10均在真实隔离事务／假供应方中执行。最慢准备5.46／5.24／5.08秒；不能把与之前不同组合的时长比较当严格性能百分比。

最终backend/app Ruff format500文件通过；schema_inspection.py Ruff lint通过。实际用户库／整版端到端／正式OS或供应方未执行，不以本批结果替代它们。

## 原来源pin及资源字节

按原tools/schema-v20-release.py发布db20-r48；manifest bf188e05df22f548ebb2e6dfab10132ba198ecea7240d4a312d14ca1579e5a39。旧r44—47保留，无校验降级。fresh.v1.sql、upgrade-151.v1.sql、objects.v1.json与r44原字节一致；摘要分别：

- 9da3375bcaed99e9b492f4fda04119eef78dcc5784c2b5daf13ac118f28957ad
- 9abcb2a3a7f662b4ca61733cb3bd34d4b894f848db2240fe7b4940e75ddb671c
- 62eeeaee0ce469548abc4b4916a39c41dd28e2040b2c88c8ff035203988540c5

仍为Schema200与固定SQLite3.54.1，不初始化、升级或写用户数据库。临时输出自动清理，仅保留本Markdown。
