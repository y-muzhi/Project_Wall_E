# Schema词法复用与逐事务核验性能 V1（V2.0）

2026-11-13香港15:56，原模型网关回归的有界线程诊断定位到schema_inspection.sql_tokens，未见等待供应方或锁死。原模型授权10项136.62秒通过，最慢准备13.48秒。现行Schema200含299个对象；每次数据库事务完整核验时重复解析完全相同的SQL文本，不能以扩大测试时间或削弱核验作为产品性能修复。

## 输入、输出和不变量

仅同一进程中的纯SQL字符串→不可变token tuple词法转换可有界复用。缓存键为完整原字符串，case／字面量／运算符／注释的原规则保持，异常不缓存；不缓存connection、数据库路径、schema_version、PRAGMA、SchemaSnapshot或核验“通过”。长度超过8192字符的SQL直接执行同一原解析器，不驻留；LRU最多512条，避免无界保存任意DDL。

inspect_schema／verify_schema每次仍在原显式事务读取实际sqlite_schema、table_xinfo／foreign_key_list／index_list／index_xinfo／table_list，并与固定完整对象清单比较。DDL变化、不同数据库、同名不同定义、另一连接改结构仍必须拒绝；相同文本token重用不能成为数据库身份或结构已通过的证据。词法扫描器原算法不改，不新增兼容解释或忽略检查。

## 实施和检查

先保存原算法到具名_scan_sql_tokens，sql_tokens按长度选择同一纯解析器及其LRU。覆盖冷热同规则、非法引号／注释重复拒绝、长文本不驻留、固定Schema完整实际事务和跨库／跨连接DDL变化拒绝。运行受影响原词法、存储、Schema200／正常启动及模型网关／授权专项；按原来源发布器生成新资源，SQL和objects原字节必须与r44—47一致。正常用户库／服务不动，不将时间改善写成整体验收或真实模型证据。
