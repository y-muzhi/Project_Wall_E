# V2.0 Git本地配置读取实现绑定

日期：2026-11-05；状态：PENDING／实施细化，未合入正式设计。依据BE0.17-draft-17第7.7.1—.2。

输入为固定Git对已持有原配置字节的私有副本执行config --file <副本> --no-includes --null --list并成功结束后的完整有界输出；调用方仍须持有原路径／文件身份，核对无config.worktree及布局／指纹并证明命令实际结束。本解析器不执行Git、不读取配置路径、不提供运行准入。

按NUL分记录、首个LF分键值；无LF为Git的隐式布尔true，空输出只表示成功读取的真实空配置，不表示缺文件可忽略。严格UTF8和完整终止符；限制完整输出字节／条目数。按7.7.2的精确键白名单逐项验证；描述值只在内存检查，不进结果／错误／审计。重复的结构性项必须逐项与同一布局相符，不能借最后一个值掩盖不符；纯描述多值可保留在解析输入，不成为命令参数。

首期布尔只接受Git文档的标准true／yes／on／1、false／no／off／0／空串及无等号true，忽略这些ASCII值的大小写；其他数值／表达式不在首期白名单。logallrefupdates另接受always；branch.rebase另接受merges／m／interactive／i，仅描述，不执行rebase。repositoryformatversion仅0／1，objectformat仅sha1／sha256，refstorage仅files，且与实际布局绑定。缺少结构键按Git默认0／非bare／sha1解释后仍须匹配调用方真实布局；sha256必须formatversion=1并有精确objectformat，不把空配置冒充sha256。

输出仅为非秘密ConfigFacts：解析输出SHA256、条目数、object_format、bare及repository_format_version；这不是原文件摘要或整个配置隔离证据。include/includeIf、worktreeConfig、任意路径／执行／签名及其他未知键均拒绝；固定错误原因不回显任何原键值。后续受控Git调用及仓库登记必须接此验证，不能仅以该组件通过标记Q20-GIT可用。
