# V2.1默认计数复验与额外开销校准

2026-11-19（Asia/Hong_Kong）。用户优先本地试用、OpenAI随后；明确授权默认v33单次1模型请求/2必要计数/139264总Token、0重试，通过后启用试用。另明确外发目的地为火山北京tokenization/chat/completions，载荷为固定合成电影推荐样本、项目通用Prompt/阶段指引/模板结构/输出Schema，密钥仅作认证，不发送真实用户需求正文。前两次自动审批拒绝均未创建进程；补充目的地/载荷授权后的唯一实际执行session23698，启动器54052/实际333308，2026-11-19 22:32:55启动，现exit1（按门槛停止）。

## 本次真实结果

原始正常DB/count-audit位于data/v21-ai-compat-04，保留[自动报告](ai-compatibility-default-2026-11-19-v4.md)及其attempts/reviewer原样。全部槽只读统计：LLMUse1、计数prepared/finished配对1、call_no=attempt_no=1，0自动重试、其余59 NOT_RUN。未超139264总硬上限。

输入26483/输出1353/合计27836 Token，缓存0，usage全已知；counts前两项23840/1002，文本合计24842，实际gap1641，发送前预计（含1024）25866。因此原v33的1024门槛仍失败，Run FAILED/CONFIG_INVALID、validation NOT_STARTED，未采用/未启用。完整OutputDiscuss Schema、basis_ref、restore_counted事后只读核对通过；错误不是返回JSON结构非法，STRUCTURED_REJECTED是执行器通用分类。正文/Revision/步骤/原Closure保护PASS。

真实观察已消耗本轮单次模型许可；不能用余1计数续测或再发请求。v33原资源/旧v4清单/本次审计未重写为通过，用户业务Run1/2/3未重放。

## 新校准候选

[独立迭代](../../iterations/pending/v2.1/WALL-E.结构化请求开销校准迭代_V_2.1.md)仅对未来新v35/v36提出framing_reserve=2048：将实测1641向上取整至1024整数倍，余407；这不是对所有Schema/输入的上界证明。旧1024失败保持。输入131072/输出8192/总139264预算不增，预检反而提前多预留1024，文本可用空间更少。实际usage仍逐次硬校验，超新门槛仍停止。Prompt/SDK/模型/计数文本/Wire及全部权限/事务不改，新release仍OFFLINE_READY，未借旧证据导入准入。

| 配置 | manifest SHA256 | release SHA256 |
| --- | --- | --- |
| 默认v35 | 84290d277cc220452ce3e7889eb8a8a5275c957e8f868018ca884516d1c167fc | b436b57722c659e56cdbb4faa18ec5cda5fb9c53a313c73313f9a71854943a64 |
| 长v36 | 60dc7351f1fbac1886b7ace1a8765ff698b8118f543b129a296beed51068266c | cc43b8e05cd513bcd809c58de64743d38f4b39b277c8caf4254a844356c5c631 |

修改源：formation/resource_schema.py固定新CountingDefinition预留；build-formation-resources.py；资源加载器新pin/默认v35/v36/历史精确选择；formation_evaluation清单说明及execution/关联测试冻结绑定。无DDL/固定构建源更改，正式设计不合并。

## 冻结与离线检查

新默认evaluation-inputs-default-2026-11-19-v5.md原SHA9f37d702210773988c1d4c0893ba37f075bf43fb63fd0e116d5e1b271c11fabf，cohort94bd411166e60c30973bcb493eb7413f0e000e2ce0bd533d0a43a84b4117873b；长组65763100c59917fe4147bb44cd132024ad352ddf6aec4c3b506cd1de956e6964，cohorta275d184f10d170c02a3e7d8f1340f0a1324e9fbfbb66c6352e97d2d752d8d48。Recipe34d60fa8ed24f85f315901ecaae6747bd5c1dc6b30f073c59d2d3529e3eeaa0e。

两组各60样本/120候选生成及--verify完整重建一致，Tokenization/Chat均0、cleanup=True。六新准备表均60行NOT_RUN/PENDING/UNASSIGNED，不当真实效果或人工结论。

固定SQLite、quality_python外网/用户data/.env隔离，临时目录成功失败自动回收。资源/原冻结选择/计数运输/预算专项56 passed、3 subtests passed，117.36秒，cleanup=True，既有Starlette/httpx弃用提示1。反例覆盖：旧1024仍拒1641、新2048接受离线数值但拒2049、输入131073/输出8193仍拒、同131072硬上限预检更严格，不能把替身数值通过称真实新release兼容。

另两份v31/v33真实原审计restore_counted及profile.request按原资源还原一致，原1024保持。初次生成v35因旧CountingDefinition.const仍1024拒绝，未落盘；更新新Schema声明后一次生成v35/v36成功，旧资源无改。

单次执行器/观察准入及原C01/C07专项结果另在完成后追加。后续新候选仍需另获单次许可，拟data/v21-ai-compat-05及ai-compatibility-default-2026-11-19-v5.md，目前未创建/未执行。

## 试用状态

2.1的5174/8001保留，旧5173/8000已停止。用户库正文及失败Run保留，未切服务或加载AI凭据，无Git提交/推送。AI尚未启用，OpenAI尚未开始实施。本地试用目标未完成；只有新候选真实技术复验通过后才导入同release原始证据并切服务，单例也不替代正式60效果/双人评价/长输出。

## v37/v38同步修正及最终离线结果

v35/v36先前只修改CountingDefinition，未同步Admission.reserve；完整观察准入专项3失败/12通过70.32秒，均离线，失败是真实资源合同错配。原资源不改，修正新resource_schema的Admission.reserve与Builder release.admission.reserve同步后发布**v37/v38**作为当前默认；v35/v36及v5清单仅作失败追溯，不用于真实执行。

| 当前配置 | manifest SHA256 | release SHA256 |
| --- | --- | --- |
| 默认v37 | bf4376487589a057492b0aedd872ebb134b151612caba492b39679052b18e4fb | 491da1a44a0d28a4c2fb7fe7ad2a809fda7650610278c961c5178cf63d2ff5cf |
| 长v38 | 14b1b626f891b65d325d0b449aaf64a9e9a3a288514995ed2440f0fba5a3e09d | 11a04d69c2fa2716062da96b854acddaf8b64dd53d398d8411bc0199c16e88b3 |

两份新v6完整清单各60/120生成及--verify重建一致，所有过程Tokenization=0/Chat=0/cleanup=True。默认原SHA65c2e9133ee7d1cf2a6481673114a23838650cfbeb1e5e14e4b678113bb3eaba，cohort93fb92d41875729ba06f23ff19b0d04030ceea5e4cec49f984e9424d7578b5e4；长组86c41d4c09481b61cfdad4a389c40617d7b8e9456a4decbb029d7b49351030c9，cohort84363ecf9514c2d7f30c956871fd3ec4b676acdb71f4cbd7fec0801e4a6cb13a；Recipe04cba9d5530baabbee05abc1d737c62cd898ab8a3a786b7437cdf9c1cdcc4350。六份v6准备表均60行NOT_RUN/PENDING，执行器及关联测试已绑定v6；v5不能继续使用。

最终：
- 预算/准入字段一致性/资源/运输/额度专项**57 passed、3 subtests passed，143.77秒，cleanup=True**；包含前56项回归，不累加。新增反例直接验证CountingDefinition、release admission、Admission Schema三者同为2048，仍OFFLINE_READY，不能用离线构造对象取得生产LIVE。
- bootstrap/真实C01/C07技术观察与后续隔离调用/执行器只发1次并保留59 NOT_RUN：**15 passed，92.23秒，cleanup=True**。修复后新组exit0，原3失败仍留证。
- 589个app格式与改动F/I/B、diff检查通过，执行器默认metadata匹配、0凭据/0调用；清理工具dry-run JSON0/截图0。v27—v38全部资源文件按各自manifest逐字节核对一致。正常库LLMUse0、3个Run均FAILED，用户正文及需求未动。
- 没有新的真实请求、技术准入导入、服务切换或浏览器可用性结论。前述本轮唯一真实请求27,836 Token仍失败，不能按新门槛重标通过。

下一步候选单次复验拟data/v21-ai-compat-05、ai-compatibility-default-2026-11-19-v6.md，未创建。需要新的1请求/2必要计数/139264 Token/0重试授权，固定火山北京两接口与合成样本/通用Prompt/指引/模板/Schema范围不变，密钥只认证；通过后沿原技术证据导入及同库服务切换启用本地试用。否则不启用/不补发。OpenAI仍随后。
