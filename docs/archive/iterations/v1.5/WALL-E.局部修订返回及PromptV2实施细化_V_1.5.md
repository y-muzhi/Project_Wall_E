# V1.5局部修订返回及Prompt V2

2026-10-22。实际局部选材只发送目标范围，原实现却要求完整正文返回，模型无法可靠补回未读全文。按正式设计局部读取与程序权限边界，明确完整性相对于本次scope：DOCUMENT／GENERATE为全文，SECTION为含标题的完整章节，BLOCK为目标区块，SELECTION为只修改选区的完整所在区块。程序按冻结身份嵌回，不能猜测局部／全文或扩大读取。

规则合入后端AI-OUTPUT及Prompt第五段。新增resources/v10，common Prompt v2／release v2；89类型及其Schema、指引、结构、8项计数规则保持既有字节。v9全部保留，不覆盖旧资源；新release仍OFFLINE_READY，不沿用真实准入。

document_application._scope_markdown确定局部含义，沿原精确范围／边界／模板保护提交；范围外重复区块按冻结位置证明身份，只对授权局部做精确对齐，避免局部插入使相同外部文本失去身份。保留原目标末尾换行以处理模型省略结尾，NO_CHANGE不新增CONTENT。没有额外Chat或计数。

资源／执行22项通过；新增局部章节插入、重复外部身份、Unicode选区越权拒绝及局部NO_CHANGE共4项通过。联合范围与未验证浏览器／供应方见verification/v1.5。此迭代已合入设计；不代表整版验收。
