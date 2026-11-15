# V2.0检查标准内容结构校验

日期：2026-11-05；代码28a7c9e后未提交V2工作区。依据完整OBJ-CODE-POLICY、APP-CODE-SETUP、BND-CODE-API-08及7.6.1—.7；本批仅纯结构逻辑，不保存版本、不执行检查或产生业务结果。

## 实现

backend/app/code_tasks/check_set_content.py供原Coding设置和Testing包编译器共用，程序显式指定owner_module，客户端内容只有protocol_version／items／coverage_plan。Coding禁止ACCEPTANCE，Testing编译内容可以包含；不接收id、owner_module、version、created_at、ready或旧required_markers。

严格核对完整CheckDefinition／target／evidence_rule及CoverageDefinition／basis_ref结构，无隐式补值。PROJECT_COMMAND只能expected_exit_codes=[0]并采用PROCESS_EXIT，case_pack_ref和target必须null；CONTROLLED_ASSERTION不能使用项目退出码结论，CONTENT_INTEGRITY不带案例／目标，CONTROLLED_CASES必须有固定案例及目标。target只接受声明的模式、非空不重复command_ids及可null fixture_ref，无URL、脚本或自由参数扩展。

AUTO只映射同版本真实定义的CONTROLLED_CASES，不能把项目测试／格式／编译退出或完整性检查当作受控功能覆盖；MANUAL／NOT_APPLICABLE必须说明且无check_ids。引用身份、检查／覆盖／阶段／依据引用去重，ID／布尔／时限严格类型，有界有效UTF8／JSON，空字符拒绝；依据quote保留原字节语义的文本，不作为显示名称规范化。空集合可作为未就绪结构保存的输入，不产生空集通过或默认检查。

成功产物为不可变CheckSetContent，按确定UTF8 JSON保存私有内容快照及SHA，返回value时深复制，原输入或返回值变动不能修改已校验内容。没有ready／passed属性，也不自行取得权限或创建占位资源。

## 实际检查

通过tools.quality_gate.environment、tools/python-v20.py及tools/quality_python.py在本轮临时根运行test_check_set_content.py，参数-q -p no:cacheprovider --tb=short --basetemp <本轮根>/p。Python3.13.5／固定SQLite3.54.1／Ruff0.17.3；无网络、正常数据库或凭据访问。

- 初版73通过，0.14秒；增加显示名称／说明空字符拒绝后74通过，0.14秒。
- 覆盖三类标准、Coding／Testing阶段、原快照不可变、服务端及旧结果字段拒绝、条件null、错误布尔／时限、引用及阶段重复、受控目标禁止额外URL／参数、AUTO不能采用项目退出／完整性结果、人工说明、依据结构、嵌入NUL／非法Unicode及输入限额。
- 新模块lint及backend/app 188文件格式通过。无前端改动，不重跑既有浏览器／类型／构建；不存在新UI或真实供应方结果。

测试临时根自动清理，无JSON报告／原始日志留存；只保留本文。未改正式设计、正常数据／服务或任何资源准入状态。

## 待接与边界

这只是版本内容的结构校验，不是CheckSetVersion发布、读取或执行资格。所有runner／case／环境／命令／fixture／受保护输入引用仍须核对实际不可变注册资源及清单；basis_refs须在真实DB和原任务固定依据中核实，案例覆盖／阶段适用性、每阶段required CONTENT_INTEGRITY及Testing受控功能要求在实际采用／执行／合格链路核对。不能仅以此快照宣称真实引用、设计覆盖完整或检查通过。

下一步按APP-CODE-QUERY完整读取模型、API08／14／22接版本的实际同事务原键保存、按身份内唯一版本分配、非秘密读取及真实readiness，再接前端。新增EntityKind及原成功DTO会改变Schema SOURCE_NAMES，须另发新release并回归原维护／启动，不覆盖r7；本批未做这些变更。

收尾静态核对：本轮39份验证／映射／计划／当前断点及项目历史的本地Markdown链接均存在，git diff --check通过，db20-r7实际load_release一致，w2-catalogue专属临时根无残留。未机械重跑已通过检查。
