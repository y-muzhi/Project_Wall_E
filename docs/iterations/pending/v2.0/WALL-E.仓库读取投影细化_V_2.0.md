# 仓库读取投影细化

沿 BE APP-CODE-QUERY、API03／04及 FE BND-CODE-SETTINGS 补齐 RepositoryView 字段。公共同形结构为 {id,name,object_format,created_at,root_path,latest_observation}。API03 按登记时间降序再按 ID 降序分页，root_path 固定 null。API04 用原仓库 ID 显式读取详情，root_path 投影已登记的 canonical_root，仅代码设置详情使用；不增加客户端指定路径字段或读取任意路径。git_common_dir 不公开。

latest_observation 为 null 或 {id,status,observed_at}，取原仓库已保存的最近观察，按 observed_at、id 降序稳定取首条。UNAVAILABLE／UNKNOWN 如实保留，不能用更旧 READABLE 代替。要查看观察明细继续使用 API71 的原仓库 ID 和观察 ID；刷新命令的结果仍以原 OperationView 的 observation_id 为准。两种 GET 同快照读取 DB，不访问仓库文件系统，不触发 Git 或后台刷新。
