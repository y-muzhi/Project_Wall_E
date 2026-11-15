# V2.0 原用例和固定候选内容

2026-11-10 香港时间。工作区 master 28a7c9e。按 BE 0.17-draft-17 的 7.2／7.6、API29／55／56／57、APP-CODE-QUERY，以及 FE 0.16-draft-16 的 BND-CODE-CONTENT／CHECKS。使用测试自有 NTFS、SQLite、Guard Job 和隔离浏览器。

- CasePack 严格解析了 CLI、HTTP、BROWSER 的固定数据操作。拒绝任意程序／URL、错误原文、重复用例／步骤／断言、空断言、载荷超限和非规范原字节。NTFS 原 Manifest 在读取时写锁，原版本内容变动后拒读。API55 的隔离 ASGI／SQLite 读取夹具核对原祖先、分页、不补未执行用例、输出脱敏及同引用包替换。生产 Schema200 的真实项目命令 API55 返回原空页并验证错误归属。固定包、读模型及 Schema 合计 46 项，另有 21 个子测试通过。db20-r33 增加受控 Case 的 INCOMPLETE 捕获状态，清单 SHA256 为 0809bc0be1c52027adf9f40b087294c4536db018f06ce0e36ba2ffb95683c524，旧 r32 保留。
- API57 从实际 Windows 捕获的封存候选读取原始二进制字节。隔离 ASGI／SQLite、NTFS／Guard 测试 1 项通过，142.97 秒，覆盖固定偏移／长度、末端空块、非法上跳和大小写不同路径。API29／56 使用固定 Git 起点与封存候选，通过读请求的临时回调取得经过策略及原对象核验的字节或元数据，暂无正常用户库／仓库证据。
- 复现。使用 tools/python-v20.py tools/quality_python.py -x -q -p no:cacheprovider 跑 backend/tests/infrastructure/test_v20_check_case_pack.py、test_v20_schema_construction.py、test_v20_schema_release.py、test_v20_schema_migration.py、test_v20_guard_control_git_transport.py 内 PROJECT_CHECK_DURABLE。前端 npm --prefix frontend run typecheck 与 npm --prefix frontend run format:check 通过。
- 仍待验证。现有 CasePack 为受保护解析和历史读取能力。正式案例／独立 driver 未发布，真实 CLI／HTTP／BROWSER 断言运行、独立 Testing、正常业务库、实际 SYSTEM／WFP 部署及供应方另验。


前端隔离 Chrome 使用同一工作台夹具完成 360／1280 像素的已有交互回归，并通过新用例只在展开时读取、资源错误重试、第二页、脱敏和关闭。候选比较通过明确选择前保持空态、固定读取失败后原路径重试、跨 65536 字节边界的 UTF-8 emoji、明确切换原侧、完整行对照、缺失侧与空文件的区分、二进制仅元数据。首轮用例分页夹具发回了 21 项一页，严格前端拒绝；修正夹具为每页20后浏览器退出0。浏览器运行时明确关闭，所有自有 Job 与临时输出均清理。

- 原固定 Git 起点的实际 Windows Guard／MinGit 联合 2 项通过（346.60 秒），覆盖生产原启动生成的同仓库固定起点读取与原任务调用路径。Chrome 用例目录和候选内容测试使用独立 HTTP 夹具，覆盖按需读取、失败重试、分页、UTF-8 字符跨块、空文件与缺失文件、二进制无正文。TARGET 两侧比较待 DeliveryPlan 接入。
