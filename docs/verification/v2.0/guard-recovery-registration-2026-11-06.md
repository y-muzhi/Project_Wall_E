# Guard恢复定位与原控制方登记（2026-11-06）

按用户已确认[窄恢复权限](../../iterations/pending/v2.0/WALL-E.Guard重启跨控制方恢复权限细化_V_2.0.md)实施。BE／FE DRAFT未合并，db20-r15／code20-r2不变，V2未提交。

## 已验证单元

guard_request_header.py：公共头仍为当前实际peer／owner_epoch；recovery严格两字段，只能OBSERVE／STOP／RELEASE，OBSERVE另带原observed_action；禁止当前引用冒充旧方及替换动作输入。target_scope仅保留原operation／step／nonce并选择旧控制方，不授予权限。原输入快照及wire保持当前调用者身份。

guard_controller_records.py：复用原operator-only LaunchJournal及PrivateRecordAppend，新*.controller.json严格无覆盖；实际CLIENT peer／完整Native身份和原程序FileID／字节，Guard受信程序／包引用和时间。首次登记前检查原launch及native历史，缺控制方记录的旧历史禁止补签；重启仅静态读原记录、不重开PID。发布未知保留原writer并沿相同FileID／摘要协调，不重发rename。记录不是程序准入或退出证明。

普通非提升测试、quality_gate.environment、tools/python-v20.py／quality_python.py、自动清理.tmp／--basetemp、自有Job／管道，无用户库、系统安装、旧ACL／网络或真实模型。

- 选择器＋帧／IO90通过，5.55秒。
- 首轮登记及私有记录37通过，5.17秒。
- 增加孤立native历史及容量后，全部13文件247通过、1条既有Starlette弃用警告，14.86秒。覆盖之前10文件通信／身份、控制方登记、共享私有记录及只读包。组合计数不求和。

## 紧接的未完成单元

随后按[保护包实施细化](../../iterations/pending/v2.0/WALL-E.Guard后端程序包准入实施细化_V_2.0.md)新增guard_backend_program.py，并将原登记明确拆为record_peer_facts（无准入）与register_admitted（必须真实ProtectedBackendProgram lease），持久backend_admission区分原证明；无准入记录不可升级。**这部分改变发生在247通过之后，尚待实际回归**。222个app文件Ruff格式及受影响模块lint通过。

新测试已保存：test_v20_guard_backend_program.py；严格清单／完整目录／变化拒绝的端口向量与实际可写包拒绝分开，端口正向不当SYSTEM或生产包证明。首次运行被自动审批服务403拒绝启动，属于review服务失败，非风险判定；未绕过审批。继续核对并重试正常审批，未将未执行检查填通过。

仍缺实际受保护walle-backend.exe构建／安装、SYSTEM／跨用户准入、旧控制方退出或可靠封闭的权限门及原Registry生产派发；不得从记录或元数据引用放行。ready／runtime_admitted=false，无新增HTTP或UI验收。

## 后续回归已取回

上述程序准入区分及原登记修改随后实际回归通过，最终15文件309通过16.91秒，见[程序包记录](guard-backend-program-2026-11-06.md)。审批服务正常重试恢复，无当前审批阻塞；真实保护包正向仍未取得，不将端口正向当准入。
