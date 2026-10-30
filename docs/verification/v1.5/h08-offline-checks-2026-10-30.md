# H08离线自动检查专项

日期2026-10-30（Asia/Hong_Kong）；HEAD8c3f025加本任务变更。Windows、Python3.13.5、Node24.15；无真实API、用户库或用户服务变更、提交／推送。

## 实际检查

1. `python -B tools/check-v15-offline.py --only runner --only frontend --only typecheck --only build`：7自检、420前端、类型、临时构建通过，见[首次部分报告](quality-gate-2026-10-30-101930-003880.md)。
2. `python -B tools/check-v15-offline.py`：前四步通过；后端250通过、2失败、10个subtest通过，耗时1243.71秒；源码摘要在执行期间一致，临时根清理成功。见[完整运行原报告](quality-gate-2026-10-30-102014-139302.md)，保留FAILED，不事后改为PASSED。
3. 启动用例独立诊断复现：1失败，堆栈定位ResourceCatalog.collaboration→ModelProfile.selected_profile。原测试以非法字符串填充模型名称／版本，与H06已要求的精确配置校验冲突；正常用例保留旧密钥、采用合法模型名称／版本，并新增非法模型必须在读凭据及启动前拒绝的用例。未放宽产品校验，未改业务启动代码。
4. Windows路径探针：原隔离根下document-long-specification的准入文件路径258字符可写；analysis-required-over-budget的路径260字符FileNotFoundError。新增总隔离层导致超过Windows边界。运行器临时前缀由walle-quality-缩为wq-，增加真实最深文件写入／删除自检，不缩减评测样本或删去失败用例。
5. `python -B tools/check-v15-offline.py --only runner`：修复后8项自检通过，见[运行器复检](quality-gate-2026-10-30-104543-104270.md)。完整／部分、零测试、非零退出、超时、取消、外部连接／非临时SQLite／凭据拒绝、清理及源码变化等结果边界覆盖。
6. 使用同一quality_python保护、wq-根及1800秒限额，定向复检test_v15_evaluation_tool.py、test_v15_startup_tool.py：16项通过，236.44秒，源码摘要一致，临时目录清理成功，见[定向复检报告](quality-gate-2026-10-30-104605-080925.md)。原始输出仅工具控制台／内存，不落原始日志。

## 交付与限制

统一入口tools/check-v15-offline.py，工具实现及测试在tools/quality_gate.py、quality_python.py、quality_node.cjs、tests/test_quality_gate.py。完整入口后端选择30文件，前端420测试；不等于历史全版本、全部浏览器或真实模型语义覆盖。

CI使用只读权限、Windows2022、锁定依赖、项目.venv路径、同一入口及Markdown任务摘要；本地前端的Python联测依赖此路径，因此工作流必须创建.venv。工作流修正在完整运行结束后完成，静态核对命令路径；远程安装／运行与分支必需检查未执行，不宣称CI已启用。

Python审计钩子允许回环供测试框架使用，拒绝外部网络／正常data及非临时SQLite；Node主检查拒绝网络。此保护针对可信测试防误调用，不是恶意代码的OS沙箱；前端唯一Python子进程为纯文本规范化对照，经源码核对无网络／数据库调用。强制结束父进程或断电不保证报告与清理。

本轮仍有既有Starlette/httpx弃用提示；依赖升级不在本任务范围。前端包体优化与真实性能、H01／H07效果和体验评估按原决定安排，不由本次程序通过替代。


## 收口结论

测试程序与仓库内CI配置完成；完整运行发现的两项失败经定位修复，8项运行器自检及两个受影响后端文件16项复检通过。完整原报告仍保留FAILED；没有在修复后再跑全部后端，也不宣称取得修复后的单次完整PASSED报告。其他250项后端、420项前端、类型及构建依据本轮此前实际运行，不能与复检重复相加作为独立用例总数。

临时根全部由本轮所属上下文清理；原完整报告及两次部分报告均清理True。cleanup-test-artifacts.py --dry-run为JSON0／screenshots0；git diff --check无空白错误。正式设计仅新增FE8.4／BE8.2各一段，原换行保留，资源及业务实现未改。远程CI、依赖重新安装、用户服务和真实供应方均未执行。
