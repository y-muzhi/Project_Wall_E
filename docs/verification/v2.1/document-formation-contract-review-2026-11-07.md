# V2.1文档形成主线0.6核心契约结构核对

日期：2026-11-07（Asia/Hong_Kong）。任务M21-FORMATION-01；云端HEAD为8c5df4c6683e10c265e2f719a4fdc09ba4210ea0。仅设计契约核对，无产品测试／模型／数据库操作。

## 范围与环境

新增[核心Schema](../../iterations/pending/v2.1/schemas/formation-contract.v1.schema.json)及[契约与验收附件](../../iterations/pending/v2.1/WALL-E.文档形成主线实施契约与验收清单_V_2.1.md)，主草案更新0.6；同步V2.1索引／计划／断点／映射。Schema是设计输入，不是测试报告，不被当前产品或冻结模型资源加载。Python3.13.5、项目.venv中jsonschema4.26.0，无新增依赖或网络请求。

## 实际执行与结果

- 执行.venv/bin/python /tmp/walle_v06_validate.py，Draft202012Validator.check_schema通过；66个定义内部引用均可解析，10个根DTO；原四个legacy补丁定义与冻结来源逐项相同。
- 50个结构用例末轮通过：22个预期接受、28个预期拒绝。覆盖当前状态／完成事件／Artifact、原设计switch／complete／apply／formation_delta示例、写入互斥模式、公共范围、未知字段／动作、初始化互斥、错误安全详情、历史游标和时间。
- 初轮无效月份被默认format检查器接受，检查失败。环境缺有效date-time格式检查；验证脚本显式登记标准库datetime检查后末轮通过。未为了通过而删掉该反例；未来运行校验器也必须显式启用格式检查。
- 3个结构接受例特意包含未解析身份、未实际携带的材料别名、错误版本算术，说明这些必须由真实程序守卫拒绝。本轮没有执行产品守卫，不能写成这些业务校验通过。
- 原子保存采用同目录临时文件、flush／fsync、替换前原内容核对、os.replace及临时清理；修改前后核对1220份受保护输入摘要不变，含代码／冻结资源／正式设计／归档／V1.5管理和HTML原型。另核对V1.5四份管理文件与HEAD一致及正式FE／BE既定摘要。
- 文档核对命令python /tmp/walle_v06_docs_check.py：31个主章节各一个、5个JSON示例可解析、全部V2.1相对文件链接、一个当前断点和git diff --check通过。

仅上述结构／文档检查实际运行；A01—A30是未来产品验收输入，全部未执行。未改HTML故未重复浏览器；无业务源码／旧Schema／冻结资源／正式规格变更，无正常数据读取、迁移、模型／计数、服务探测／启停或Git提交推送；未保留测试JSON、截图、录像或原始日志。

## 遗留与接续

核心DTO不等于完整资源发布。新purpose／私有binding、完整GET／Canonical／Wire／Output和目标DDL仍需收束；真实V2.0基线、首步启动／联合动作选择、容量验证和新release准入仍未完成。继续先读[当前断点](../../project/v2.1/实现进度_V_2.1.md)，不得将结构通过当产品功能或升级验收。
