# 固定提交完整文件遍历（2026-11-06）

HEAD28a7c9e，V2未提交；BE0.17-draft-17／FE0.16-draft-16及db20-r12不变。依据BE7.2.1—.2／.6和7.7，接续现行进度及pending实施细化，未合并设计、修改用户数据或服务。

新增git_fixed_content.py／inspect_fixed_tree；从明确commit读取根tree，逐完整路径展开所有目录及普通文件，复用ContentPathIndex／ContentEntry／ContentLimits。共享子树和blob在多个路径出现时分别枚举和计量，空目录仅做命名空间核验；实际目标路径240 UTF16约束、普通mode、文件／总字节／文件数／枚举数及原时间预算失败即整体失败，不排除已跟踪内容，不创建manifest／内容包／基线。

git_commit_closure.py提取OriginalObjectReads，共用原请求／有界IO、OID及格式、原来源／取消／截止和累计读取预算；历史的_Inspection保留原调度及去重，不复制第二个进程调用流程。文件检查回调必须由可信调用方显式提供，无默认允许；回调返回或异常后再核对原资格。输出仅不可变文件元数据，不保留正文。

按[官方Git LFS指针规范](https://raw.githubusercontent.com/git-lfs/git-lfs/main/docs/spec.md)核对UTF8、字节上限、完整有序键、OID及size，拒绝v1及文档列出的旧URL指针，覆盖扩展键；不fetch／smudge。普通源码仅出现版本头而无完整指针时不误拒绝。空树的枚举预算与commit header限制分开。

## 实际检查

Python3.13.5／SQLite3.54.1／Ruff0.17.3及固定MinGit2.56.0.windows.4。专属TemporaryDirectory，tools.quality_gate.environment及tools/python-v20.py tools/quality_python.py，-q -p no:cacheprovider --tb=short和临时--basetemp。

- 初轮四纯文件123通过0.50秒：backend/tests/code_tasks/test_git_fixed_content.py、test_git_commit_closure.py、test_git_object_graph.py、test_git_object_read.py。
- 加backend/tests/infrastructure/test_v20_git_metadata_command.py::test_raw_commit_tree_blob_and_tag_conversion_use_original_native_chain，两格式真实Native共125通过96.46秒。遍历器实际驱动原RepositoryObjectCommand／AsUser／Job／管道读取固定commit、tree、blob，指纹持续核对；文件内容、大小及元数据一致。所有自有进程／Job依原owner清理。
- 复核后收紧LFS从头匹配改为完整指针判断，修复小枚举预算误限制commit header；新增正常说明文字、扩展指针及单根空树预算检查，最终四纯文件126通过0.36秒。此后三处局部逻辑由专项覆盖，没有把前一125写成修改后重跑；实际Native向量为普通非LFS内容，其原读取链路未再改变。
- 最终209后端文件Ruff格式、两个修改模块lint及git diff --check通过。文件均同目录temp、flush／fsync、原字节复核及os.replace。
- 内容专项覆盖两格式、重复子树及blob路径计量、BOM／二进制／CRLF不转换、空树／缺失对象、文件／枚举／路径预算、文件检查缺失／异常／非确认返回、来源／时间变化及LFS。既有闭包／对象解析回归同时覆盖。测试回调是夹具，不是实际秘密策略准入证据。
- 无前端变化，不重复前端或浏览器检查；既有httpx提示保留，未升级依赖。

## 剩余边界

实际不可变secret_policy_ref资源、目录准入、原业务调用方／保留引用／GitReceipt、物化及REGISTER_BASE仍待接。组件不授予模型读取／执行资格，runtime_admitted=false；业务HTTP仍18条。无正常库／用户仓库／.env.local操作、真实模型／计数、用户服务启停、既有ACL或网络策略修改、提交／推送。仅保留本Markdown，临时根及JSON／捕获按所有权清理。
