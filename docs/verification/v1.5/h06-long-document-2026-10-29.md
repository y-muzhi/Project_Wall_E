# H06 长文档出稿专项验证

日期：2026-10-29（Asia/Hong_Kong）。代码：HEAD422cc98加现有快捷键、H03—H05及本轮M15-LONG-01工作区变更，未提交。环境：Windows／PowerShell、项目.venv Python、Node24.15、Chrome155无头；没有真实Tokenization／Chat、用户数据库写入或用户服务更新。

## 实际改动与边界

- 新增deepseek-long-v3：输入131072、输出32768、总量163840，framing1024、零重试、读超时仍180秒。默认仍deepseek-v2／v15／8192；显式WALLE_MODEL_PROFILE选择与资源同步。新配置上限不保证一次生成完成，超时及其他失败保持原处理。
- 新资源v16：CountingDefinition v2、contract v4、release v8；Prompt v6及同key/version的其他资源原字节保持。manifest `8a4a16de358eb66a6d057ffba4e54fd3b2e696d4673754cfe1435b0bb79ebc5e`；release `8c218ea79f3ef14c778a0581fddfac8ba65e8c1fc1902936244ff4a13f512027`。状态OFFLINE_READY，旧真实准入不能放行新配置。
- 历史profile按完整快照恢复，历史release精确选择；请求详情、结果恢复、事实确认按原预算检查。新配置不放宽旧请求，未知release／修改过的快照拒绝。
- 框架创建入口带入名称／类型，章节列表绑定实际当前内容版本和标题block_id。REVISE／SECTION每次只保存一章；选择下一同级章跳过子章、在上级边界结束，不自动发送或推断完成。支持重新绑定最新版本；UNKNOWN状态配置保持冻结。
- 截断保留模型原文和原正文，不创建半份文档。摘要明确未写入及分章路径，NOT_APPLIED摘要默认展开。

## 程序检查

| 命令／范围 | 实际结果 |
| --- | --- |
| `python -B -m pytest -q -p no:cacheprovider --tb=short backend/tests/guide/test_v15_long_output.py` | 最终10项通过，56.76秒。profile／环境／快照、预算／usage边界、准入拒绝、历史读取、两章后第三章截断、明确观测额度、整篇截断零文档 |
| 同一pytest入口：test_v15_counting、local_revision、execution、recovery、model_calls、admission、observation及infrastructure/test_collaboration_resources、test_model_profile_audit_data | 首轮87通过、1失败、10个subtest通过，385.32秒。失败为旧默认v15对照新设计的断言；调整为新v16对照设计，并单独还原旧计数定义核对旧v15完整bundle，未删除旧保护 |
| `python -B -m pytest -q -p no:cacheprovider --tb=short backend/tests/infrastructure/test_collaboration_resources.py` | 修正后27项全部通过，9.21秒；与前述回归重叠，不重复累计 |
| `node --test --test-isolation=none tests/v15-ai-composer.test.mjs tests/guide-composer.test.mjs`（frontend） | 26项通过：含新章节配置、明确发送、版本变化、UNKNOWN不能切章和下一同级章边界 |
| `node --test --test-isolation=none tests/*.test.mjs`（frontend） | 420项通过，6988ms，0失败／跳过 |
| `node node_modules/typescript/bin/tsc --noEmit`（frontend） | 通过；接续后再次确认最终代码通过 |
| `tools/serve-v15-offline.py`私有测试包装内Vite build，输出到独占临时根 | 两次临时生产构建均通过；没有覆盖frontend/dist |
| 修改Python AST、v16所有文件digest及与v15相同key/version身份核对 | 通过；Git已跟踪历史resources无修改 |
| `python -B tools/observe-v15-once.py --profile deepseek-long-v3` | 正式CLI离线预览通过；release为新v16，输入131072／输出32768／总量163840，count_batches_sent=0、chat_calls_sent=0；临时库退出清理 |
| 当前变更文档相对链接及`git diff --check` | 501条链接0缺失（冻结H03原始归档不重写相对链接）；设计README新增CRLF提示已规范为LF，最终diff检查退出0 |

后端检查的Starlette／httpx弃用提示保持，未为此安装或升级依赖。首次pytest路径误写为不存在的test_model_profile.py时未执行任何测试，随后使用实际test_model_profile_audit_data.py。新专项第一次沙箱运行3项无库检查通过，5项SQLite fixture在锁文件创建和清理时权限错误（10个setup/teardown错误），不是业务断言失败；获自动批准后同组本机权限运行8项通过，补充两个边界后最终10项通过。原失败没有改写。

## 隔离真实浏览器检查

采用Playwright技能／已有CLI0.1.22，无依赖安装。真实页面、HTTP、SQLite和事务，AI仅为进程内私有模拟Counter／Gateway；不含供应方效果或真实32768输出证明。

1. 零文档需求→对话生成设置→“创建框架，分章撰写”：名称带入，新建窗口预选固定框架；此时AI请求0次。
2. 创建七章框架V1→“分章节撰写当前文档”：首章明确为REVISE／SECTION。
3. 填写并发送第一章，实际请求document1／content_version1／heading_block_id1；保存后提示使用最新版本。
4. 选择第二章不发送请求；明确发送第二章，实际请求document1／content_version2／heading_block_id2；保存至V3，第一章和第二章正文都在，其余五章保持原框架。
5. 再选择第三章，仍只有上述2个POST guide-runs。选择最后第七章，“选择下一章”禁用，不循环。
6. 1600×1000流程及1100×850窗口：章节控件区域clientWidth=392、scrollWidth=392，无横向溢出；复检期间pageerror=0。未覆盖所有浏览器、键盘／读屏组合或超大章节列表。

首轮完整保存失败原因：旧离线Gateway用next查找可写paragraph，但新框架只有heading，模拟返回前就抛出异常，文档仍V1、运行FAILED／INTERNAL_ERROR。修复tools/serve-v15-offline.py的框架章节模拟分支后，以全新隔离库重走以上流程成功；不将这次夹具错误归为产品或供应方故障。首轮截断保护及连续两章后截断的证据来自后端专项，不冒充浏览器已测截断。

## 中断、服务及清理

第一次临时根walle-h06-browser-bd7w2tdy：原生Python PID44056、端口56043；浏览器walle-h06。期间自动审批先因使用额度不能完成，接续又两次超时；均没有执行被拒操作，按允许重试完成。浏览器空闲退出后重开，先核实真实记录再操作，没有重复提交未知请求。

首轮关闭浏览器后向所属PTY4880发送stop，输出模拟count1／Chat1，进程退出0，父进程确认临时根清理。第二次临时根walle-h06-browser-z150bgt8：PID42520、端口53399、PTY37720；复检后浏览器关闭，stop输出模拟count2／Chat2并退出0，父进程确认清理。两次合计3个模拟count及3个模拟Chat，真实调用均0。父进程仅管理本次创建的子进程，备用超时终止未触发。

父进程包装及浏览器流程脚本仅临时存在，结束删除；CLI配置／YAML／临时前端构建／数据库随临时根删除，不保留原始日志或截图。首次沙箱失败目录在收尾只读枚举中已无匹配目录。`tools/cleanup-test-artifacts.py --dry-run`结果JSON=0、screenshots=0。正常数据库、审计、冻结资源及生产dist保持。

## 未覆盖与后续

未执行真实模型／计数、新profile准入、用户服务切换或生产资源部署。当前默认配置保持8192；新配置不能因离线测试通过自动LIVE_VERIFIED。正式FE／BE已按职责合入，具体操作见[运行说明](../../operations/v1.5/运行说明_V_1.5.md)。H01统一语义评估仍按用户安排延后，H06不能据此记为真实长文档效果已验收。
