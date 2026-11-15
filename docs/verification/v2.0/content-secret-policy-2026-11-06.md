# 固定秘密策略资源与实际接入（2026-11-06）

HEAD28a7c9e，V2未提交；设计BE0.17-draft-17／FE0.16-draft-16保持DRAFT。依据7.2及ConfigurationOption.value的CONTENT_POLICY原契约，具体首版规则先写入[独立pending](../../iterations/pending/v2.0/WALL-E.Git历史读取与当前内容校验实施细化_V_2.0.md)，未合并正式设计。

新增content_secret_policy.py及backend/resources/code/secret-policies/content20-secrets-1.json。CONTENT20-SECRETS-1原字节SHA256为9962434a0d9ef12497db9d3ee1984eec66f2321a5c6122ff85ad777b888d63a1，程序编译pin固定；只按已知引用／固定路径有界读，不接受客户端规则、正则或资源路径。解析为冻结tuple后检查路径与原blob字节；未知引用、缺失或改动都不能退化为空策略。异常只给SECRET_RESTRICTED，不记录命中路径／正文。

首版明确拒绝.env／.env.*（含示例文件）、.netrc、credentials.json、id_rsa／id_ed25519文件名、.aws/credentials后缀，以及五种PEM私钥头字节；Unicode casefold路径匹配。规则是有限检查，既可能拒绝含私钥头的说明文字，也不承诺检测所有未知令牌、加密或编码秘密；变更需新版本，不在运行中悄悄例外放行。

git_fixed_content新增正文读取前的路径检查。inspect_registered_fixed_tree绑定真实策略，禁止调用方替换check_path／check_file；命中整次拒绝，不删除文件或静默排除。真实注册入口与原RepositoryObjectCommand／Native／Job组合，不以测试自由回调冒充策略。

复用现有CodeCatalogue／ResourceCatalog及API20，发布不可变code20-r2，manifest fbc6fb9295f59e1c9e5bfd1841c9d753060c42f18958ed3b7e80e4dd68bda7c2；新增一条CONTENT_POLICY仅公开版本／引用，不返回规则匹配内容。ready=false，Q20-CONTENT／GIT／WINDOWS保持，未把资源生成当整体捕获／Windows准入。r1未覆盖；历史r1可显式读取，新目录需唯一固定策略项。Schema SourceNames未变，db20-r12及manifest 0996b4ebc744f63b49c1b777970acd816911e216bdf3ca9c70fe446b86d0a310实际load_release通过，无新Schema或正常库维护。

## 实际检查

Python3.13.5／Ruff0.17.3／固定SQLite3.54.1／MinGit2.56.0.windows.4。通过tools.quality_gate.environment、tools/python-v20.py tools/quality_python.py，-q -p no:cacheprovider --tb=short和专属临时--basetemp，普通非提升隔离环境。

- test_content_secret_policy.py、test_git_fixed_content.py、test_configuration_options.py及test_v20_git_metadata_command.py::test_raw_commit_tree_blob_and_tag_conversion_use_original_native_chain两格式，共65通过159.50秒。前三文件在backend/tests/code_tasks，Native在backend/tests/infrastructure。
- 覆盖原资源hash／缺失／未知引用、禁止路径在blob读取前拒绝、五种私钥头／二进制正文命中、无正文诊断、不可替换回调、安全二进制保留；实际API20读取已发布目录，真实两格式Native遍历使用注册包装器；全体ready仍false。
- 最后按lint合并等价条件，并补策略文件篡改的真实ASGI检查，前两个纯文件加test_configuration_options.py::test_real_policy_resource_corruption_is_not_an_empty_catalogue，共31通过4.71秒。API返回503 CONFIG_NOT_READY／data=null，不能当成功空目录。与前组重叠不求和；Native未为排版改动重复运行。
- 最终210后端文件Ruff格式、content_secret_policy／code_configuration_catalog／git_fixed_content三模块lint及diff检查通过。原子保存均同目录临时文件、flush／fsync、原字节核对和os.replace。既有httpx提示保留，未升级依赖。
- 首次直接执行准备脚本因项目导入路径缺失未发布资源，改经tools/python-v20.py后成功。单独核对时曾先导入业务模块导致SQLite激活保护拒绝，纠正为先激活再导入后实际三份pin核对成功，没有放宽运行库保护。
- 当前无活动检查，w2-content-*最终0；SQLite、原配置副本、JSON和Git进程／Job按原owner清理。正式策略JSON与目录JSON为产品资源，保留原字节，不作为测试报告清理。

未改前端、正常data／.env.local、用户仓库、系统策略或既有ACL，未启停用户服务、发真实模型／计数、提交／推送。业务接口仍18条。后续仍须原REPOSITORY OperationStep／真实观察生产、REGISTER_BASE保留引用／GitReceipt、策略与完整配置／来源资格绑定及物化；此处不代表基线登记或完整2.0验收。
