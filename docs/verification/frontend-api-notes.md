# 前端业务绑定及实际API浏览器验证（2026-10-05）

`frontend/src/api/walle.ts::WalleApi`绑定13只读/24写接口，按公共定义配置method、路径、空体/JSON体、状态码及幂等头。写动作一次捕获完整原输入及响应核对条件，再产生同一不可变动作；用户明确重试仍用原键/原请求。I04属性与I11保存无幂等头，其余写入按原定义；草稿expected_version不替代CURRENT版本。PATCH/可选字段缺省仍缺省，不补null；后端合法普通文本标准化不会被客户端误作字面不一致。响应身份/所属、接受/取消/批次状态及版本依实际返回核对；分页仅列表允许，普通读与所有命令出现分页拒绝确认。

`models.ts`覆盖Requirement/Summary、实际解析的Document与Revision/Summary、Guide状态/历史/接受、完整消息与卡片/正式响应、评论/定位/全文index、建议/批次/完整counts。字段白名单/安全ID/UTC/条件null、重复及完整统计核对后返回隔离冻结数据。卡片及五Patch评估冻结ASK_OUTPUT公用defs的实际结构，语义键/选择/推荐另外核对；未修复或截断数据。文档与历史必经已注册真实Milkdown `validateDocumentReadModel/validateBlockState`，不使用shape代替Markdown配对；实际来源对象关系仍由后端同事务保证。损坏结构null消息保留正文回退与服务端card_state，不猜测可回答性。index包含全部未删除评论，没有虚构10000评论容量限制；10000仍只限制实际文档区块。传输层补齐登记error.details白名单，非法拒绝响应保留未知结果，500/503可能已提交仍未知。

[前端完整59测试/TS/依赖/development检查](frontend-2026-10-05T10-05-17-112Z.json)通过，64输入前后hash一致。新增19测试覆盖37方法/路径/请求体/头策略与原后端注册路由逐项匹配、完整模型/合法与恶意变体、实际分页/游标、同动作getter只读一次/外部变更/丢响应/原键重试/新动作新键、响应归属与错误详情。Node网络响应是显式诊断夹具，不是业务服务或产品联调证据。

[实际浏览器API联调](api-browser-2026-10-05T10-05-05-334Z.json)通过，291个backend/frontend/shared及两探针工具输入前后hash一致。标准ApiClient通过Vite同源代理请求正式create_app/uvicorn与隔离SQLite；真实创建、属性更新、草稿开始/取消/三次保存/完成、初始化BASELINE、人工版本/历史、评论完整流程/统计、AI接受/失败/重新运行及生命周期均可查询。37接口实际到达，39个记录是I11重复三次；I15/I17在已失败运行返回STATE_CONFLICT，I20–23/I36使用真正不存在的资源返回NOT_FOUND，不能据此声称建议应用或真实卡片回答成功。所有4运行缺配置真实FAILED/CONFIG_INVALID；Native正常关闭后实库requirements=1、CURRENT=1、revisions=2、软删comments=1、guide_runs=4、LLMUse=0。7份实际文档/草稿及1份历史快照经过真实Crepe解析配对，draft version=4/CURRENT=2且历史source_version=2。没有静态假业务响应、生产库或Provider付费请求。

首轮浏览器业务链完成但结束统计写错物理表名documents导致整体失败，保留[失败记录](api-browser-2026-10-05T10-02-55-218Z.json)。已改用既有requirement_documents并重跑全过程；没有修改业务表、返回或断言。探针只在output/playwright创建全新显式隔离库，通过测试stdin IPC关闭，没有新增公共关闭接口；自己的浏览器/Vite/API进程均已关闭，数据库诊断文件保留。

后端730完整记录范围保持，本批没有修改backend代码。59与37到达都不等于373原设计场景完整验收。尚缺自动保存/未知结果复查/本地恢复、轮询、完整公共组件、工作台/详情/导航/窄屏/焦点/IME/布局、构建与干净安装、备份审计保留部署，以及真实计数/Provider/效果。下一步继续这些工程，原计数补充稿仍待用户确认和真实证明。
