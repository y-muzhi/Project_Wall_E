# 固定交付commit输入及真实Git对象（2026-11-05）

代码为28a7c9e后的V2未提交实现。新增infrastructure/git_commit_input.py及test_git_commit_input.py，扩展既有固定Git向量worker和专项。依据BE3章DeliveryConfiguration及7.7.3，正式设计未改。

输入为采用配置的作者／提交者／模板、原task／candidate／delivery ID、原BUILD固定Unix秒数、已核对的格式／tree／expected parent及容量；输出不可变原payload、SHA256及Git commit OID。不读取环境、个人身份、当前时间或工作树。模板仅两个字面ID变量，拒绝属性／索引／格式表达式／转换；消息统一LF、保留空白并补唯一原Delivery尾注。姓名／邮件UTF8非空、拒绝控制符和头分隔符；单parent，无签名或其他头。

恢复先核长度／SHA／GitOID，再核原tree／parent／Delivery、四行头、同一原秒数／+0000及唯一尾注；不重新渲染模板、取新时间或采用新配置。空body、巨长时间等明确拒绝。原input_ref保存、业务资格、Plan仓储、Guard命令、引用事务及HTTP尚未接入，此算法不是交付完成。

## 实际检查

- 默认隔离环境、固定SQLite启动器＋quality_python：test_git_commit_input.py **54通过，0.16秒**。
- 获准普通环境、同启动器：上述专项＋test_content_manifest_git_vectors.py **55通过，4.46秒**。完整固定375项MinGit字节校验后，在自有Job的新sha1／sha256 bare中构造独立父提交和交付commit；hash-object -t commit --stdin --no-filters计算／-w写入OID相同，cat-file原字节相同。生产BUILD SHA256／GitOID／字节数匹配独立worker向量；同一路径继续核对blob／tree。
- 170个生产文件Ruff格式、新模块Ruff check及git diff --check通过。既有Starlette httpx弃用提示保留。无本轮临时目录／活动进程残留。
- 只写新临时库内未引用对象，不更新正常仓库／引用／HEAD／索引或用户内容；原始JSON及测试库自动清理。未调用真实模型／计数、未改服务或系统策略。

runtime_admitted仍false。Git协议一手来源沿用[固定包记录](git-bundle-bytes-2026-11-05.md)；先前原blob／tree证据见[内容记录](content-manifest-git-vectors-2026-11-05.md)。本轮只补原字节和对象证据，不扩大为配置、Guard部署或交付验收。
