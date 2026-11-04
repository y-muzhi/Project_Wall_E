# V1.5交互文档归并接续静态核对

日期：2026-11-01开始，2026-11-02完成（Asia/Hong_Kong）；文件名保留任务开始日期。环境：现有Windows PowerShell、Python与Git。代码状态：master，HEAD 8c5df4c6683e10c265e2f719a4fdc09ba4210ea0，初始工作区干净；本轮只修改Markdown，不提交推送。

范围及合入位置见[补合记录](../../archive/merges/v1.5/合并记录-2026-11-01-交互归并接续复核.md)。pending/v1.5实际只有README；最近5份交互规则已合入，2份助手／创建来源已归档。本轮补齐文档助手在FE页面／组件／验收中的残留替代，修正映射schema151、可空根记录和两字段创建。原业务检查证据仅引用，不改原日期／失败／未覆盖。

## 静态检查结果

| 检查 | 实际命令／方式 | 结果 |
| --- | --- | --- |
| 现场与修改范围 | git status --short；git rev-parse HEAD；git diff --name-only；git ls-files --others --exclude-standard | 12份Markdown（10修改、2新增），无代码／资源／Schema差异；未暂存／提交／推送 |
| 来源及规则覆盖 | Get-Content／rg读取完整FE、最近7份来源及相关BE／前端实际调用方；Python内存断言 | 22项覆盖／旧规则排除断言通过；5份交互原已合入，助手残留按原职责补合；两字段正式规则保持 |
| 链接与锚点 | Python内存解析本轮12份Markdown的普通本地链接、显式HTML／标题锚点 | 608个本地链接、其中11个锚点均存在；无未闭合代码块／替换字符 |
| 正式基线与示例 | hashlib.sha256；git show HEAD:<正式FE>提取代码块比较 | FE／BE仍1.0 EFFECTIVE／V1.5；FE的1个原代码块保持，BE原字节保持 |
| 当前断点与归档 | Python目录清单／标题计数及归档字节指纹 | pending仅README，唯一当前断点；54份迭代正文相对任务开始字节未变，未重复归档 |
| 非文档与本地资料保护 | 任务开始／结束对1045个已跟踪非docs文件及3份V2.0／downloads来源做路径＋字节SHA256 | 两组指纹保持；AGENTS、代码／工具／资源及本地V2.0来源无本轮修改；不读取正常数据库或凭据内容 |
| 差异与临时文件 | git -c core.whitespace=cr-at-eol diff --check；Python查找本轮.docmerge临时文件 | 退出0；同目录临时文件清理，无本轮JSON／截图／录像／原始日志文件 |

FE补合前SHA256：3ea136c5c1fd72d739ea8cb6e38dd3e2ae704523ccf730f02599f749f4dc564f；补合后：b294153e11ef764f36f92b7390dc817c6ed079a81734c770ebe6f217601e2920。
BE保持：36d2e28630b5099a30253e5a5881492c8fc50c3cffaf4d9d4a88341bdc24defd。
非docs指纹：93195ab88c3d6aa022198322a2799f807ab88185b3961d9e0a07df33351f11dc。
本地V2.0／来源指纹：0be51acc37df441e3a591e1983a97f9e7f4b3a7c7fdaf9becbdf41056d20e9bd。

## 失败、修复与未覆盖

首个文档编辑脚本在内存替换阶段发现README的CRLF与LF匹配差异，已停止，未写入任何文件。统一在内存处理换行后再按原换行／编码原子保存；所有写入均同目录临时文件、flush／fsync、关闭、原字节并发复核及os.replace，成功／失败清理本轮临时文件。

首次静态检查将工作区归档字节直接与Git对象比较，6份原有CRLF／LF差异被误报；没有修改这些文件。改为核对任务开始保存的55文件归档指纹（仅在内存撤去README新增导航段以复原其起始字节），结果仍为81766302ad9b18141110b04df535984d09f3da3929a9c7a7c2042524f9d7a63c；另核对54正文与Git规范化内容一致。最终检查退出0，无缺失链接、锚点或规则。

本轮只核对文件内容、引用、归属与变更范围；未执行产品测试、类型检查、构建、浏览器、真实模型／计数，不能证明当前浏览器、服务或供应方可用。完整跨文档引用管理UI、原H项／人工语义及多浏览器缺口保持原状态。服务启动仍沿tools/ai-service.py --start --credential-file .env.local及frontend下npm run dev，本轮未执行或枚举进程，旧PID不作为当前存活证据。
