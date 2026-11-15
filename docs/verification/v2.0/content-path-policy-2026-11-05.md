# V2.0内容逻辑路径与完整树别名检查

日期：2026-11-05；HEAD 28a7c9e。已完整阅读BE7.2、7.3、7.4、7.7规则；当前单元只实现CONTENT20-STORE-1逻辑路径，不声称Git／Guard／捕获已就绪。

实现content_paths.py：有效UTF-8／原NFC、不规范化改名、正斜线相对路径、Windows保留名／特殊字符／控制码／尾点尾空格、.git控制目录拒绝；仅100644／100755。ContentPathIndex核对全部隐含父目录与文件的Unicode casefold别名、重复及文件／目录冲突，完整校验后再变更索引，失败不留下半条记录。UTF-8字节序返回完整条目，原大小写／模式保持。物化完整路径固定240 UTF-16单元，计入绝对根、分隔符和非BMP字符。

专项：tools/python-v20.py tools/quality_python.py backend/tests/code_tasks/test_content_paths.py -q -p no:cacheprovider --tb=short --basetemp <专属临时目录>，45通过（0.09秒）。首次普通执行环境在TemporaryDirectory退出阶段报WinError5；随后按确切绝对路径及父目录核验，独立检查Test-Path为False，确认本次目录已不存在，没有泛删Temp／Packages。测试通过与首次清理异常分开记录。159文件Ruff格式及git diff --check通过。无测试JSON／截图／原始日志保留。

现场与来源：[Git for Windows官方发布](https://github.com/git-for-windows/git/releases/tag/v2.56.0.windows.4)正文的MinGit-2.56.0.4-64-bit.zip SHA256与设计一致；当前个人PATH Git实测2.51.2.windows.1，未用来取得Q20-GIT或执行产品仓库操作。dotnet --list-sdks无SDK输出（仅找到dotnet host），不推断原生编译工具已可用。没有下载安装系统Git／Guard或修改系统策略。

剩余：路径算法不替代实际打开后的NTFS文件身份、ADS／EFS／离线类型、ACL、文件静止、秘密策略、include／exclude完整规则、Git对象／模式／LFS／包清单／容量及读取。固定Git包来源／完整字节和真实程序／Guard／配置隔离仍需后续单元；不把纯逻辑专项作为Windows或完整内容捕获验收。正常源仓库及用户Git引用未操作。
