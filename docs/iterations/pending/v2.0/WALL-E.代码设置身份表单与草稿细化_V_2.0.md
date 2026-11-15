# 代码设置身份表单与草稿细化（2026-11-07）

沿 FE BND-CODE-SETTINGS 和 INF-FE20-BROWSER 实施执行配置／检查配置身份列表、创建及固定版本读取。正式设计未写设置草稿完整键，本次补为 sessionStorage 的 walle:v2.0:code:settings:{origin}:{EXECUTION_PROFILE或CHECK_SET}，内容 {schema_version:1,name,updated_at,command_key}。每个分区独立，保存失败保留当前输入并提示；不把普通草稿暂存当命令已提交。command_key 初始为 null，仅关联本草稿实际保存的原意图。重新编辑时解除关联。迟到的原 201 核对时，仅在原键和冻结名称摘要均与当前草稿匹配时清除草稿；后写的同名输入也保留。

沿既有 CommandRecovery／CommandRecoveryStore 同一流程，新增 stageIntent 返回原持久 reserve 的 PREPARED／EXISTING／RESOLVED 事实；stage 现有调用行为保留。创建按钮只对本次 PREPARED 意图提交。发现同入口已有待核对原请求时不自动派发，不用当前表单替换原正文。明确恢复和关闭仍属于待核对区域。新身份保存后保留真实 ID，再读取其版本；没有版本时显示该身份暂无版本，不能据身份创建或“最新版本 ID”推断可执行。
