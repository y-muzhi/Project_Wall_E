# V1.5 收口静态核对

2026-10-25，Windows PowerShell／项目.venv。仅整理导航及持久断点，不改业务代码、模型资源、正常数据或服务，不新增供应方调用，不提交推送。实际v15执行时源码与后续只读入口收口源码分别沿用startup-catalog-closeout-2026-10-24.md的记录，不回写原证据。

- `git diff --check`退出0；仅两份既有Python文件提示下次Git操作将CRLF规范为LF，没有空白错误。
- `python tools/cleanup-test-artifacts.py --dry-run`退出0，项目可清理JSON=0、截图=0；正常业务／计数／准入证据不属于测试报告。
- `Get-NetTCPConnection`只读核对8000／5173，无监听；未启停任何用户服务。
- 以项目相对POSIX路径排序，将每个路径UTF-8及对应文件SHA256二进制依次聚合：本批技术及EV正常SQLite／JSON共112份，SHA256仍为`d6c73a4bbc8c98049d34cec887757bd947eb2cfbd311d8071653a73a754ecc92`。
- 六份当前入口／运行文档的95个本地Markdown链接均存在，无异常控制字符。移除导航页重复的过期阶段摘要；原验证记录保留，效果评测准备页明确分开当前结果和历史申请。

本次没有重跑既已通过的离线／类型／构建或真实验证。程序结果见[live-verification-v15-once-2026-10-24.md](live-verification-v15-once-2026-10-24.md)，非AI收口检查见[startup-catalog-closeout-2026-10-24.md](startup-catalog-closeout-2026-10-24.md)。人工语义按正式BE8.3仍待逐项判定，见[审阅入口](manual-semantic-review-v15-2026-10-24.md)；用户库配置、服务启动和生产静态部署未执行。旧16个临时目录的自动删除审批拒绝保持遗留，未绕过。
