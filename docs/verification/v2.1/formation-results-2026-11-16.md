# V2.1成果依据与结束处置检查

开始：2026-11-16 22:18（Asia/Hong_Kong）。独立工作区codex/v2.1-design-review，HEAD a0f4059及连续未提交实现。本批仅落实已有前后端0.1-draft-4规则；不合入正式设计、不调用真实模型／计数、不修改正常库或用户服务、不提交推送。

本批已于次日00:10收口：后端314／前端649、格式／类型／临时构建与下述实际产品路径已通过；整版验收未完成。下文按执行时点保留，“待回收／进行中”等描述仅是当时状态，最终结果见末节及[覆盖审查](acceptance-coverage-2026-11-16.md)。

## 实现范围及不变量

成果页分开正文关联与分析成果／依据；当前步骤评估标记当前性，来源与分析要求不等于完成事实。高级结束明确选择CONTENT的真实关联或ANALYSIS的真实来源；缺省空处置依旧可一键结束。消息及版本走原20项服务器分页，选项跨页保留、最多100来源、去重，关闭来源读取不产生业务写入。不可用步骤来源另行说明，不伪造成无数据。结束快照固定event_id、原定义及原来源；最多20成果只读取一个有界原页，不预取无界历史。提交前发现D/F/V/定义／目标变化时保留选择并提示重新核对；已发送操作复用同库schema5精确恢复。

输入为真实StepDetail及用户选择；输出只有既有COMPLETE_STEP与原回执。后端独立核实LANDED／ANALYZED，不凭UI声明更改正文。实现位置：frontend/src/formation/result-state.ts、result-dispositions.tsx、evidence-picker.tsx、analysis-results.tsx、detail-view.tsx、closure-view.tsx、page-view.tsx及progress-view.css。

## 已执行检查

- Node新增formation-result-dispositions.test.mjs：4 passed，351.53ms；缺省空处置、取消未完成声明、CONTENT不能用分析来源冒充落地、跨页100依据／101拒绝、原冻结请求不受后来变更、定义变更及重复依据。原completion/history＋target/composer18项通过，1.23秒。
- 严格类型已通过；首轮图标名不在现有集合及只读数组不能直接作为可变JSON的问题已修正，未放宽类型。整文件源码写入失败时原文件保留，补齐fieldset配对后原子保存。
- 固定Python入口tools/python-v20.py tools/quality_python.py，test_v21_completion_commands.py＋test_v21_closure_snapshot.py：10 passed，45.42秒，原结束／完整Closure事务回归。TemporaryDirectory及quality_gate.environment；无真实供应方、无正常业务库。
- 受限执行环境的本地Uvicorn启动两次超时；第二次栈定位到asyncio本地socketpair初始化（业务fixture已就绪），未运行产品请求。随后以本机连接可用的隔离方式执行同一临时环境，安装quality_python离线／数据库／凭据读取保护；实际成果页纯查看0写已观察。
- 首轮可启动的浏览器专项在检查脚本的嵌套定位器超时；已按实际结果项的aria-label修正，非产品故障。完整提交／冷恢复浏览器结果仍待回收，未提前算通过。

## 待补证据

真实LANDED＋ANALYZED、消息跨页／版本选择、丢回执＋reload原body/key恢复及固定Closure证据；新页面窄宽／错误／无内容／版本变化等。最终类型／格式／完整前端／临时构建在本批源码稳定后执行。本记录不代表整版A01—A76、14表单、极限／多窗口及供应方语义已验收。


## 实际产品闭环（22:42）

完整RequirementDetail／Milkdown／WalleApi＋隔离Schema210 API，使用真实LINK_CONTENT和ADD_RESULT事务夹具。成果页独立分析要求、正文关联，纯查看0写。明确选择LANDED缺关联、ANALYZED缺来源均禁用确认并说明；31条真实消息跨两页选择两条，再选固定Revision，共3条依据，翻页／换来源不丢选择，选择过程0业务写入。

一次COMPLETE_STEP提交同时携带s1.o1/a1与s1.o2的3条真实来源；服务成功后模拟客户端丢回执，UNKNOWN保留。真正reload并按原请求核实，body/key逐字一致，持久pending归零，仅一次服务写入。原正文DOM在结束时保持，正文V1未变化。实际结果页固定event6读取：s1.o1=LANDED、s1.o2=ANALYZED；分析来源3条。展开结果记录前不预取Evidence；明确展开才GET event6/RESULT/s1.o2/evidence，不向当前来源拼历史。控制台Errors0／Warnings0，自有API8217、Vite5187、Chrome和所有临时数据已清。

脚本修正记录：首轮等数量2而预期3来自未明确等待异步换页／来源列表，改为等待新页实际首项及对应类型后3条通过；原请求数组按实际选择插入顺序，检查改按result_ref核对，不假设数组下标；步骤完成文案是既有“已结束”，脚本曾误用“已完成”，修正后通过。上述均未通过改变产品去迎合检查。

本批此刻全量前端647 passed（6.56秒），严格类型1.44秒通过；最终格式／临时构建结果继续回收。其余新UI空错态／实际并发及完整14表单继续按独立单元推进。

## 双窗口冲突、空错态与支持宽度（22:48）

真实第二窗口对s1执行START，本窗口仍按旧D提交COMPLETE收到409；没有成功的Closure写入，分析选择保留。复查发现原observeSummary在F变化时会清空规范detail，导致Overview卸载及表单丢选择，已修复实际页面生命周期：规范读状态保持严格，页面只缓存同一选中身份的一份最近成功详情，并明确旧数据／加载／失败；新详情READY前依赖旧详情的原生动作和结束禁用。

修复后实际双窗口复验通过：表单内重读保留同一条已选依据，版本变化时确认禁用，明确“已核对当前版本，保留选择”后再提交成功。最终s1.o1=OUTSTANDING、s1.o2=ANALYZED，V1不变、pending0；未借此自动声明文档成果已完成。为此在表单内增加只读刷新、明确保留重核及明确清空重选入口；UNKNOWN仍不允许重做新操作。

步骤依据成功空数据使用本模块EmptyState；注入消息GET失败时显示真实错误，没有伪造“无讨论”；点击刷新后恢复并保留选择，选择过程0写。实际1024×900弹窗client/scroll均440、底部取消54／确认106宽，截图已人工查看：无横向溢出、正文和工具条不覆盖，临时截图在查看后随环境清理。此并发用例Console有1条预期409资源错误、0警告；不能称0错误，原无故障完成用例仍0错误／警告。

首次完整前端647／类型／格式／临时生产构建均通过（6.56／1.44／3.57／1.43秒）。其后仅detail-view的同身份详情保留与冲突重读发生修改，类型已复查通过；稳定后补受影响检查。当前开始14类路线实际交互及212个定义的后端formation整组离线回归，结果未提前标通过。

## 14类路线表单真实主路径（22:54）

同一完整产品／隔离Schema210环境依次实际填写、只读预览、确认保存：SET_GOAL、ADD_STEP、RENAME_STEP、MOVE_STEP、SET_DEPENDENCIES、UPDATE_RESULT、ADD_RESULT、LINK_CONTENT、MOVE_ISSUE、SET_BRANCH_RETURN、DISPOSE_ISSUE、RESUME_ISSUE、DISPOSE_BRANCH、CANCEL_STEP。每项实际PATCH，最终14种各1次，正文V1、pending0、Milkdown同一DOM；Console0错误／0警告，自有服务和所有临时数据已清。

包括：ADD临时步映射s32；调整原成果及新增ANALYSIS；真实Revision区块关联；问题及支线转交；问题暂缓后明确恢复；支线暂缓；跨第二页选择s32取消并为其全部成果填写NOT_REQUIRED及原因。只代表每类一条成功交互，预算边界／全部非法组合／所有窄宽及占用矩阵仍按后续验收，不称14类全部边界已通过。首轮脚本把动态字符计数拼进固定label而超时，改为业务标签匹配后14项通过，未修改产品来迎合脚本。

后端formation整组首次受限环境仅打印4个进展后停滞477.69秒，结合相同环境已定位的asyncio本地socketpair限制，停止了核实身份的自有子进程树；外层finally临时目录已清理，结果是中止，不是通过。随后在本地连接可用且保留quality_python离线／库／凭据保护的同一隔离方式重新执行；结果尚在回收。

## 1001步骤与1001遗留的实际分页（23:04）

隔离夹具1001真实存储步骤／1001开放问题，各问题携同一真实消息来源。完整产品主线首页total1001、items20、DOM20、0写，首读约4.97秒；连续51页到s1001，最大DOM20、最后1项、0写，50次翻页约9.32秒。查看s1001后返回首页并直接结束s1，一次PATCH实际保存2成果、1001问题Closure，无模型／正文写入。Closure问题51页到i1001，最大DOM20、最后1项，50次翻页约5.12秒；未展开前Evidence请求0，最后明确展开i1001才读取其固定来源。

Console0错误／0警告，自有服务／浏览器及所有临时数据清理。首次规模检查在连续翻页的内部状态等待处超时，未取得诊断；无产品改动的加诊断复查已完整通过，保留首轮超时事实，不把单次通过扩成全部时序／性能矩阵。夹具首次还遗漏json导入，启动即失败后已修正，仅检查脚本问题。

上述耗时仅本机隔离一次观测，不承诺性能SLA或生产用户规模。1001步／遗留读取与完整Closure已取得浏览器证据，1001节点替代链及全部组合仍未验证。

## 来源及显示复查

已补齐三处REVISION SourceRef必须的block_ids=null：成果原始正文、路线当前版本原文、历史复核当时版本。不放宽公共SourceRef/readSource校验。随后已用真实离线C01/C07连续3次复核产生a1→a2→a3→a4链并实际检查这三个来源入口，结果见下一节。

同身份详情缓存进一步绑定FormationWorkspace对象，不凭不同文档重复的s1身份共享。结束快照和路线预览的问题状态改用原issueLabels，显示“未解决／已解决”，支线继续用branchLabels，沿设计已有文案，不改业务枚举或事务。

## 四节点替代链及三个固定版本入口（23:10）

夹具通过真实人工编辑与3轮离线C01→Counter夹具→Gateway夹具→C07逐次生成a1→a2→a3→a4，不直接伪造复核记录或替代边；每轮均确认APPLIED。这里的模型／计数全部是本地替身，不是供应方效果证据。

完整产品默认只显示当前a4，明确勾选已替代项后4项可见；从a1打开替代历史，4个真实节点与前后关系完整。展开a1被替代时的事件仍显示a1→a2，没有改成a1→当前a4；该事件“查看当时核实的正文版本”实际读出V2，当前a4原始正文及路线所选版本原文实际读出V4。三个此前漏字段的来源入口均实际成功，不靠放宽SourceRef校验；浏览器全部操作0写，Console0错误／0警告，临时库／审计／服务／浏览器已清。

初次检查对带“当前讨论”后缀的步骤按钮用了不带后缀的精确名称而超时，随后按真实步骤身份定位通过，非产品业务故障。此结果覆盖4节点链，不扩大为1001节点替代链或全部生产规模性能。当前代码继续在独立工作区，未提交／发布。

## 后端formation整组回归（23:19）

固定SQLite入口tools/python-v20.py tools/quality_python.py backend/tests/formation -q -p no:cacheprovider --tb=short --durations=10 --basetemp <owned-temporary>/pytest：314 passed，1条既有StarletteDeprecationWarning，1398.22秒（外层1399.01秒）。当前backend业务源码／core r54／target r7在本批未变；此整组覆盖严格契约、存储、原生／路线／结束、AI接入及发布／采用、来源维护、当前／历史／分页、复制升级和显式启动等实际专项。不能把314个程序检查自动换算为A01—A76所有浏览器及真实供应方场景通过。

使用本地连接可用的隔离环境，仍在quality_gate.environment／quality_python限制下，禁止外网及正常库／凭据文件读取；所有临时库、计数审计、子进程输出和测试产物在finally清理，无原始报告留存。已有弃用提示本轮不升级依赖解决。

## AI建议的来源、过期原因及人工操作独立（23:28）

按既有5.1规范补概览中的评估／建议来源入口、建议动作及程序返回的具体stale_reason；原说明／真实回复来源保留。只读SourceList去重、每页20，展开才创建来源读取入口，未点击不发来源GET。分析页同步显示评估过期原因，不以AI判断覆盖程序成果状态。

真实离线C01/C07产生UNCERTAIN评估＋COMPLETE_STEP建议；首步按既有用户讨论接受规则IN_PROGRESS，没有被AI建议结束。实际查看建议及原来源0写；手动PAUSE后显示OWNER_STATE_CHANGED对应中文，恢复步骤仍可用。再通过真实路线表单SET_GOAL，评估和建议均显示GOAL_CHANGED，仍可明确恢复步骤。Console0错误／0警告，浏览器仅PAUSE PATCH、无key只读预览POST及ADJUST_PATH PATCH；无新增模型／计数，全部自有临时数据清理。

检查脚本最初错误假设用户已讨论的首步仍PLANNED，后改按真实规则检查“没有自动结束”；暂停后按钮应为恢复，旧脚本查暂停超时后修正。另一次内部状态等待超时未定位，无产品改动的加诊断复验完整通过，保留该事实，不把单轮通过当全部压力时序矩阵。

## 多取消草稿与实际拆分、合并（23:30）

新增两项Node行为先复现失败：第二个临时重复取消改选或移除时，第一项仍需要的成果去向被清掉。已修复path-editor按其他取消操作判定归属；清空目标清旧详情，移除操作清其读取／详情，不接受晚到读取，不清其他操作的真实说明。原6项＋新2项共8 passed（366.61ms），严格类型通过。

实际完整产品从s1的CONTENT／ANALYSIS拆成s32／s33，完整填写两项同kind去向、两个问题去向、带关联问题的支线返回及正文区块复用，一次路线保存：s1=CANCELLED，s32/s33各1问题，s32支线1／新关联1，V1。再实际合并s32/s33到s34（CONTENT＋ANALYSIS），两项取消均保留各自完整去向，一次路线保存：s34问题2／支线1／关联1；支线origin仍s1、return=s34；原a1归属s1、a2归属s32及原Revision3均保留。实际读取4条RESULT_ROUTE事件全部为真实s32/s33/s34成果身份，无临时符号；两次保存、正文V1且Milkdown同一DOM。Console0错误／0警告，临时环境已全部清理。此为真实组合，不把14个独立表单成功替代拆分合并证据。

## 键盘、嵌套弹窗与最终检查（2026-11-17 00:00—00:10）

实际键盘检查发现原生summary未被公共焦点循环收录、子弹窗Esc向父层传播、成功结束后原按钮消失以及父面板关闭时恢复焦点早于普通面板挂载。已在shared/modal、shared/confirmation及实际formation事件路径修正；不改变事务、命令正文或Schema。发送中取消按live owner.phase判断；展开后关闭延后一微任务且核对目标仍连接／可见／不inert，避免晚到恢复抢焦点。相关summary目标至少32px。

最终完整产品检查：Tab到达“前置步骤（0）”，反向循环到达“步骤来源（0）”；子层Esc保留父层且焦点正确。实际持有发送回执时，父层和确认层均原生open且可见、inert=false，确认层aria-busy=true，Esc不取消在途命令。成功COMPLETE使原按钮消失后焦点仍在父层；关闭展开面板后回到实际展开入口。一次临时完成写入、Milkdown同一DOM。Console0错误／0警告，自有环境完整清理。

实际Vite读取6个相关模块均200且有关键内容：detail-view/resetCompletionChoices、path-editor/hasOtherCancellation、source-list/FormationReadSources、shared/modal/summary选择器、shared/confirmation/activeModal、progress-view/queueMicrotask；返回模块均非空。初次检查对原生dialog误用role可见性／disabled判定，已改查native open、实际布局、inert与aria-busy；不把脚本判定错误写成业务失败。

前端最终全组649 passed（5.02秒）；其后仅目标32px及格式调整，最终format:check通过（3.64秒）、typecheck通过（1.52秒）、临时生产构建通过（1.12秒）。closure-view曾有格式提示，原子格式化后最终通过。没有为纯CSS／排版重复整组功能测试。后端本批最终仍为314 passed，无后续backend生产代码变化。

最终完整性：两份详细设计原SHA256、core/r54、target/r7以及v27/v28 manifest共6个固定项全部匹配。资源生产加载器CollaborationResources.load重新校验完整文件／契约／semantic release digest，v27/v28均OFFLINE_READY。首次检查错误地把semantic release digest当原文件SHA比较，检查脚本已按生产规则纠正；没有因此改资源或固定项。正式设计、资源默认选择及正常用户服务未更新。

本批已按A01—A76逐项整理[覆盖审查](acceptance-coverage-2026-11-16.md)，相关测试文件存在或通过不等于全部原始场景通过；全读屏／状态矩阵、更多晚到组合、六正文入口、更多历史链及真实供应方仍按该表保留。

收口维护检查：tools/cleanup-test-artifacts.py --dry-run为JSON=0、screenshots=0；git diff --check通过。当前及归档10份文档446条相对链接核对无缺失；自有测试端口5187／8217无监听。进度、映射、计划与导航已同步，未自动提交／推送。
