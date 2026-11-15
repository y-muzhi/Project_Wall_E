# V2.0候选内容选择组件验证

日期：2026-11-05。设计BE0.17-draft-17，7.2.1—.2；实施绑定保留pending，未改两份设计。工作区为28a7c9e之后未提交V2代码。

实现：infrastructure/content_selection.py。输入为固定完整基线ContentPathEntry集合、原include／exclude数组及new_file_mode；输出只为实际枚举文件的纳入／原模式决定，或明确目录剪枝。复用ContentPathIndex和relative_content_path；不复制路径清洗算法，不进行IO。

跟踪路径不受include限制，保留基线100644／100755；exclude命中任一原跟踪条目即拒绝。新增按固定模式。目录规则按完整段匹配；仅include支持“.”。重复／别名／文件目录冲突及完全遮蔽的显式include拒绝；允许include目录内明确排除非产品子项和正常父子include重叠。所有规则均核对，不让先命中“.”掩盖后面的大小写别名。合法名称的!、[]、$只按原文匹配，无glob／否定／Shell展开。编译后原输入变动不改变规则，内部映射不可写；错误固定原因不回显路径。

检查环境：项目Python3.13.5／固定SQLite启动器及quality_python网络阻断，专属.tmp临时根。命令：tools/python-v20.py tools/quality_python.py backend/tests/code_tasks/test_content_selection.py backend/tests/code_tasks/test_content_paths.py backend/tests/code_tasks/test_content_manifest.py -q -p no:cacheprovider --tb=short --basetemp <owned>。

实际132通过，0.20秒；其中选择器57项、原路径／manifest75项。覆盖精准边界、正常重叠、空include、无新文件、原可执行模式、即使后续删除的原跟踪保护、嵌套排除、缺少include仍不剪枝、重复／父段别名、输入与基线类型／冲突、Unicode／非法路径、不可变状态。新模块lint修正Mapping标准库引用后通过；最终178个backend/app格式及diff检查见Git配置记录。仅修import没有改业务分支，未重复整套。

范围：纯选择组件，没有文件打开、扫描／静止／取消、秘密检查或原生封存证据；完整捕获器调用仍待接，不能称候选已可捕获。不合成缺失文件、不自行判定删除、不发布CaptureRules或更改运行准入。未改正常数据／服务／仓库，未真实模型／计数，无测试输出残留。
