# 原提交历史闭包读取（2026-11-06）

依据BE0.17-draft-17／FE0.16-draft-16（DRAFT），两份SHA256再次复核与现行断点一致。HEAD28a7c9e，V2未提交；本单元不改正式设计、正常数据或服务。实施细化保留[独立pending](../../iterations/pending/v2.0/WALL-E.Git历史读取与当前内容校验实施细化_V_2.0.md)，不自动合并。

## 实现及范围

git_commit_closure.py接受明确完整commit根集合、原source指纹、可信原读取／来源核对／取消回调及显式程序预算。从每个commit读原父提交、树及必要blob，按OID去重原读取，同时计入全部边（含重复）；缺失／错类型／不完整／故障不返回部分闭包，也不重试或fetch。仍由RepositoryObjectCommand及原Native／Job／有界管道执行读取，不开放自由命令，不创建第二个调度器。

唯一对象、全部引用边、单对象／累计读取字节和从原准备时刻开始的墙钟分别有限额；请求将剩余字节／时间交给可信原生调用方，调用方必须将其用于捕获及原Job停止，遍历器不能中断任意阻塞回调。读取前后、最终确定序列化后都核对原source／取消／时间；本次超时不能在最终hash阶段变成成功。SOURCE_CHANGED保留为同名业务错误，其他失败不宣称未发生原进程。零剩余字节时最多用1字节探测证明真实空对象，非空即失败；不借此取得超过总预算的成功事实。

git_object_graph.py将同一二进制tree记录解析提取为decode_tree_links，历史结构可以保留原文件名字节及symlink blob而不物化；gitlink外部依赖整次拒绝。原decode_tree_edges继续CONTENT20严格普通模式、UTF8／NFC／路径／别名检查，未放宽当前选定版本。require_original_object额外拒绝bool伪装原长度。输出只含有界确定的原根／对象类型OID／大小及SHA等元数据，正文、原身份和消息不进入记录。

这证明明确根集合的已读闭包，不是全部不可达对象或tag扫描、当前树秘密策略／物化通过、仓库永久当前状态或基线登记成功。

## 检查

普通非提升Windows，Python3.13.5／SQLite3.54.1／Ruff0.17.3／固定MinGit2.56.0.windows.4。用tools.quality_gate.environment临时根、tools/python-v20.py tools/quality_python.py，-q -p no:cacheprovider --tb=short及专属--basetemp；真实仓库和自有Job均为隔离夹具。

- 初轮三纯文件110通过0.34秒：test_git_commit_closure.py、test_git_object_graph.py、test_git_object_read.py（均backend/tests/code_tasks）。
- 四文件116通过128.66秒：上述三文件及backend/tests/infrastructure/test_v20_git_metadata_command.py，含两格式实际Native闭包。原生成commit→tree→blob都由遍历器发出固定原请求、实际有界读取，原metadata指纹逐次核对，再核对每个Job退出／空集合。
- 静态复核后补最终结果序列化后的时间／来源检查、SOURCE_CHANGED编码及严格原长度类型；最终112项纯检查加上述Native文件的test_raw_commit_tree_blob_and_tag_conversion_use_original_native_chain两格式，共114通过66.56秒，退出0。前两组是早期代码结果，不能替代最终补强后的检查；各组有重叠不相加。
- 纯夹具实际覆盖四commit合并历史、共享父／树／blob及重复根去重，独立五种预算／坏值、缺失父、错误格式／类型、取消与KeyboardInterrupt、来源变化／错误时钟、最终序列化变更、外部gitlink拒绝、历史可读与当前不支持内容分离及真实空树零字节探测。故障注入只是相应边界证据。
- 既有httpx／Starlette弃用提示1条，未升级依赖。初步207后端文件格式及本轮两模块lint通过；最终pin／清理／文档检查见本次后续记录或当前断点。

当前版本仍须完整固定树内容及秘密策略校验、原REPOSITORY操作／保留引用／GitReceipt及仓库HTTP；runtime_admitted=false。没有真实模型／计数、用户仓库或正常DB操作、服务启停、安装／既有ACL或网络策略改变、V2提交／推送；所有测试JSON及捕获仅临时根，Job按原owner结束并清理，仅保留本Markdown。

后续接口／枚举修复已收束至db20-r12；最终208文件格式、五模块lint、diff及load_release通过，本轮两类临时根均0。此后Git模块未再修改；接口／实际隔离升级及前端证据见[原观察记录](repository-observation-read-2026-11-06.md)。本行是后续现场补记，不把114项写成在r12后重跑。
