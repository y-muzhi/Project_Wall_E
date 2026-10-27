# 评论定位与AI处理范围分离实施检查

2026-10-26开始，2026-10-27收尾；M15-COMMENT-SCOPE-01。基于master／48fab5b后的未提交工作区，保留M15-COMMENT-01既有修复。用户授权代码与必要检查；本轮没有Git写操作、真实模型／计数或用户正文写入。服务更新仅按后续本轮新许可执行，见收尾补记；此前来源修复的重启许可已使用，没有延续为本次许可。

## 实现与设计

C05原路由新增可选scope_mode（COMMENT／BLOCK／SECTION／DOCUMENT）。省略参数保持原规范业务输入及幂等摘要；显式模式纳入请求身份。同事务读取原评论及真实所属CURRENT，先检查有效锚点／状态／占用／双版本，再按评论区块身份派生范围。章节无最近前置标题拒绝，不猜重复文字、不回退全文。原评论定位不变，实际ScopeRef进入原接受／Canonical／计数／补丁保护；无新模型协议、资源或永久评论授权。

前端原评论卡片内设置，复用SingleSelect／公共动效。打开／选择／收起不提交，取消丢弃未发送选择；另一评论与新操作默认原范围。刷新版本或评论变化后须明确核对范围；发送及UNKNOWN冻结原动作。真实NOT_APPLIED在实际回复旁提示未生成建议且正文未变；真实建批才进入原审阅。API省略模式仍可精确重放旧原请求。

实际代码：backend/app/guide/{contracts,http_models,commands}.py；frontend/src/api/walle.ts、comments/{commands,panel-owner,panel,command-control}、guide/read-view、messages/timeline、shared/styles；requirements/panel-read及detail-frame。新增检查在原test_v15_comment_guides、v15-comment-guide、comment-panel及panel-read专项。

正式FE／BE仍1.0／EFFECTIVE。FE前SHA256=ccedbe7f4b6208b9cedc77c9b477e2f22641557da32a8337a772979d724c07be，后SHA256=a8cc0e8fb14aae99d379969b314b4772a99cac5eabae6b99bae4bd82fa2d5a6c；BE前=5bbd4728ac854aef3aba327e1cb6854c1ce6315667b769e07fd3080672d8e50b，后=92f7798339f0c12b403b803682dc7bf7255e46e252b707a6759b68df0bb00f28。BE代码围栏及引用模型原文与HEAD逐块相同，冻结资源无差异，v15 manifest保持a8c5087236d8e4b4b40d62a92643832fe37cc2b5e426725f1ddde7d5670abc40；正式文档保持原LF字节方式。

## 离线与构建

后端命令：`.venv/Scripts/python.exe -m pytest backend/tests/guide/test_v15_comment_guides.py backend/tests/guide/test_v15_acceptance.py backend/tests/guide/test_v15_counting.py backend/tests/suggestions/test_v15_batches.py -q -p no:cacheprovider --tb=short`。实际通过包裹pytest.main的TemporaryDirectory运行，tempfile.tempdir指向本轮工作区独占临时根，退出均清理。

- 评论初版19项通过114.72秒；最终HTTP增加省略／显式DOCUMENT参数化，共20个评论用例。扩大四文件回归中41 passed／2 failed／213.39秒，两处失败源于测试的invalid mode循环遮蔽参数化变量；修正测试变量后仅重跑该2项，2 passed／7.74秒，最终适用43项全部通过。不是单次43项全绿记录；没有为测试放宽业务约束。
- 覆盖原锚点／四范围、重复标题／重复文字的真实区块身份、无章节、生命周期、归档及双版本、旧省略幂等精确重放、同键改范围拒绝；同一选区外补丁在COMMENT拒绝而DOCUMENT建批，实际正文先不变，程序采用后无额外Chat；全文必要材料超预算保持全文范围、0 Chat。原来源复用回归继续通过。
- 前端相关评论29项通过352.214ms；最终全量`npm.cmd test`为399 passed／7402.525ms，含新增3项面板读取取消专项；`npm.cmd run typecheck`退出0。
- `node node_modules/vite/bin/vite.js build --outDir ../walle-v15-browser-zbeli8ie/frontend --emptyOutDir --logLevel warn`退出0。输出仅本轮独占临时根，未覆盖frontend/dist；只有既有500kB chunk提醒。

先期受限环境默认临时目录拒绝创建锁文件，随后工作区独占根下同步用例能执行，但异步执行停滞，已中止并清理；受审查离线运行环境下正常。测试编写中的草稿保存回执字段、解决评论回执编码、模拟Headers及暂停评论读取夹具已修正。以上均保留失败原因，不当成产品通过证据。后端既有Starlette弃用提示未新增处理。

## 实际隔离页面

使用playwright技能和tools/serve-v15-offline.py --serve，真实应用／SQLite／Worker、私有Counter／Gateway、新独占临时根walle-v15-browser-zbeli8ie，随机55241／PID48644／PTY59034，命名浏览器walle-comment-scope。生产包从该临时根提供，所有写操作仅在本测试库。

- 实际生成V1测试稿，并通过正文真实选区入口创建“记录电影”四字评论。
- 打开设置、改选整篇、收起再展开，真实运行／调用数始终1／1；选项及焦点保留，1600×1000无横向溢出，临时截图已实际查看。取消后新操作恢复原范围。
- 明确提交原选区：run2真实NOT_APPLIED、无batch、V1不变；回复邻近可见“修改建议未生成，本轮正文未变”，无可执行确认控件。
- 重新明确选整篇：run3真实APPLIED／batch1，原评论仍SELECTION；通过接受／完成本批／确认应用，正文V1→V2，私有Chat总数仍3。不是直接覆盖或自动采用。
- 第二条区块评论默认原范围，未继承全文；原评论失效定位仍按既有保护不提供AI入口。run4／5仅为离线交接诊断，批次丢弃保留结果。
- 早期转AI时见过“读取失败，保留已确认内容”，网络接口均200，私有浏览器捕获本地AbortError／Read retired。为仍可见的面板增加最多一次取消后重读；离开面板不重读，实际失败或第二次取消继续失败。3项离线专项证明次数和退役边界。不能据此声称所有历史读取提示均已复现或原页面全程零错。
- 最终新包重开隔离浏览器，第二评论明确选择章节，run6真实scope=SECTION／heading_block_id=3、APPLIED；等待候选真实读取后审阅／完成本批控件可见（未决定时正确禁用完成），alerts空，最终浏览器console error／warning均0。未修改用户页或补写旧返回。

合计私有6批计数／6次Gateway，真实供应方0。最初CLI版本脚本签名／命令格式与已展开菜单脚本曾失败，未当成功动作；一次自动审批用量限制导致读取未执行，用户继续后恢复审批完成复查。没有绕过审批或复用付费许可。

## 清理、现场与边界

命名浏览器已close；PTY59034收到stop后退出0，报告6计数／6Chat及临时输出自动清理。实查临时根不存在、55241无监听，初期被拒绝的系统临时根也不存在；cleanup-test-artifacts.py --dry-run为JSON=0、screenshots=0，不保留截图、快照、录像、HAR或原始日志。

加载前用户服务只读核实：8000／PID13012、5173／PID12440仍监听；两个需求IDLE，RUNNING GuideRun／EDITING人工／PENDING候选均0；GET后端列表及前端requirements均200。用户库mode=ro，0写入。8000尚未加载本次Python变动；前端开发入口可能随Vite加载源码，服务更新需当前明确许可，不能据旧重启许可自行执行。

未覆盖：真实供应方新范围的语义效果、其他浏览器／窄屏高缩放组合、跨标签全组合，以及整版原人工语义验收。没有新增模型资源发布；旧scope模式已发请求通过省略字段与原body恢复，不做用户数据库迁移。批量评论、评论直接保存、孤立评论全文操作均不在本专项。

静态链接／差异及最终断点核对见收尾补记；本专项代码及相关离线／隔离页面检查完成，用户服务加载与真实语义证据分列。

## 收尾静态核对与获准服务加载（2026-10-27）

20份本轮变动Markdown的365个本地链接无缺失，git diff --check退出0；当前19个变动实现／检查文件按排序路径、NUL、原文件字节、NUL聚合SHA256=334031cdfaa4ba913d6889a7e3f2ef52a1cb63c03521745a084a71b1814febaf，包含保留的原来源修复。模型代码围栏／引用原文逐块相同，资源差异0。清理dry-run JSON／截图0，专项归档及映射／断点同步。

用户在代码、检查和正式文档均完成后明确授权“允许重启后端加载专项”。重新mode=ro核实所有需求IDLE、GuideRun RUNNING／人工EDITING／候选PENDING均0，端口归属为8000／13012、5173／12440；原PTY22018正常Ctrl+C，完整Application shutdown complete／Finished server process13012（Windows控制台退出1），实查8000释放后才重新启动。

启动仍为原数据库与配置：WALLE_DATABASE_PATH明确指向data/wall-e-v1.5.sqlite，安全助手tools/ai-service.py --start --credential-file .env.local内部读取凭据；未打印密钥、未初始化／迁移、未重新导入准入、未调用供应方。新8000／PID41388／PTY8803启动完成，原release/profile及预算保持，5173／PID12440未重启。

加载后6项只读GET均200：需求2的expand=discussion、comments?document_id=2&page=1、comment-index?document_id=2，前端requirements/2、src/comments/command-control.tsx、src/api/walle.ts。前端模块实际含新AI处理范围与scope_mode。复查用户库2个需求IDLE，在途三类仍0；现有GuideRun16／LLMUse16／Comment4，没有本轮新模型任务。未代用户提交评论、修改正文或点击候选。

当前服务已加载本次源码，可从http://127.0.0.1:5173/requirements进入。服务更新与只读检查完成不代表真实供应方新范围效果验收；该证据仍由原隔离检查与未覆盖项分列，Git本轮尚未提交／推送。
