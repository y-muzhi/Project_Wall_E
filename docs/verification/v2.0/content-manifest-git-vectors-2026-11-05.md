# V2.0 内容清单、原始blob校验及固定Git向量

日期：2026-11-05；HEAD 28a7c9e，V2未提交。仅自有临时目录与本轮Job；无正常源仓库、业务库、用户服务或真实模型调用。

content_manifest.py实现CONTENT20-STORE-1清单完整字段、固定策略／profile／sha1或sha256身份、原路径／模式、全父目录别名及冲突、UTF8字节排序、精确文件／字节计数，递归键序／无BOM紧凑UTF8和单LF确定序列化。解析不修复重复键、额外字段、不同字节格式或缺字段；可绑定原manifest SHA／对象格式／配置版本。按实际原字节及清单字节限制，不按压缩量或字符串字符数计。纯清单有效不表示真实Git对象／tree闭包存在。

BlobVerifier按原始分块核对长度、SHA256及Git blob对象ID，失败／完成后不能继续使用，不变更BOM、CRLF、NUL、无效文本或二进制。空文件可由零个非空chunk确认，不把读取失败当空。compare_content只按精确路径，保留缺失与真实空文件、模式变化；改名产生两侧各自增删，不做相似度猜测。原Git基线可提供临时元数据参与比较，不持久创建起点manifest／bare包。

实际检查：纯清单＋既有路径74通过（0.13秒）；最终清单／路径／真实固定Git三文件75通过（5.53秒）。后续164文件Ruff格式及diff检查见当前记录。命令为固定SQLite启动器tools/python-v20.py tools/quality_python.py上述三个test_content_*文件，配tools.quality_gate.environment及项目.tmp专属目录，普通权限。

真实CLI向量先重新核对官方MinGit原ZIP／375文件字节，再在本轮Job内执行绝对cmd/git.exe，真实version=2.56.0.windows.4。两个全新sha1／sha256 bare测试库，显式空system/global／template和允许集合环境；使用hash-object -w --stdin --no-filters、cat-file原字节往返、mktree -z真实空树及三blob完整树、ls-tree精确一致。父组件用实际OID分块验证原blob和构造完整对应清单。未使用个人PATH Git、用户仓库／索引／分支、过滤器、hooks或联网补对象。最初将大夹具放命令行导致WinError206，已改独立worker与明确owned marker／nonce，最终只保留通过结果。

所有自有根／Git子进程在Job终止并核实空后清理；临时JSON只在自动清理目录，无测试日志／截图／报告JSON保留。此为包字节＋Git CLI／对象向量层，不是生产CONTROL_GIT启动器、Guard、签名／配置白名单、LPAC／WFP或正常Git准入；runtime_admitted仍false。完整候选源句柄／秘密规则／静止、真实对象包seal／发布／恢复、基线保留引用、DB及HTTP接入仍待实现。

一手协议：[Git hash-object](https://git-scm.com/docs/git-hash-object)、[Git mktree](https://git-scm.com/docs/git-mktree)。Git树使用原生mktree排序，清单JSON排序不替代树构造。
