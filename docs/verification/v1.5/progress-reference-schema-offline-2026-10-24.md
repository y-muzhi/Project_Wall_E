# V1.5 进度依据引用Schema离线核对

2026-10-24（客户端日期）。代码：当前v12增量工作区，正式BE SHA256 ab7c7812c6ff730ee4d072c8b52e105b4c2e1792046c3ddaf4d66a2ec85644b6。

实际v11正常观测仅mode=ro读取；v12 Progress Schema明确拒绝原topic.evidence_refs中的m1／m2。诊断用内存副本将这些位置显式替成该样本实际声明的new_e1／new_e2，apply_progress纯函数得到4主题、2依据、pending清空；原对象／数据库／LLMUse不改。此副本是人工构造的离线对照，不是生产自动修复，更不是修改原供应方返回或EV成功样本。正常原返回仍REJECTED并保留。

运行方式：一次性Python只读SQLite／纯值调用，计数0／Chat0／数据库写入0。新资源release=ad5e45c5e2373ece410d699c886e887c8179ac5303368c6e2fbc668341110a2e，manifest=3db3a635d5c639d6e1406e717bd7e84d380e70cb4796464fea101477a5810312，contract及六输出v2、Prompt仍v3、89类型；与v11比较仅8项逻辑资源摘要变化（contract、六输出、release），其余13项逐字节不变。

完整25文件离线专项运行中，最终结果另记；v12真实供应方及26项EV未执行。

v12默认装载后，对原v11正常LLMUse1请求详情以mode=ro读取仍READ_OK，八分区／八计数准确，无编译或重计数。v9／v10／v11的原manifest及每份资源文件按冻结SHA256和字节长度逐项核对通过。

完整25文件最终177 passed／751.61秒，1条既有Starlette弃用提示，见offline-suite-2026-10-24-015611-653610.md。没有真实API、用户服务或用户数据操作。

其后仅修正prepare工具报告硬编码日期为Asia/Hong_Kong实际日期，同步执行器固定源码摘要；不改样本或产品逻辑。新准备源码SHA256=6b0de89db48479ef770d6cbc9d4df00a10ff0f748548359f8c72402d4066bdd3。最终26输入再次零IO预编译，与修正前26份user字节长度及SHA逐项完全相同；当前执行器preparation()摘要装载成功。CLI预览／既有报告保护／全局额度3项3.38秒通过（其余3项未重跑），不冒充又跑完整177项。最终输入记录ev-input-preparation-v12-final-2026-10-24.md，前一记录保留。

最终维护核对：HEAD=a8dc673＋本轮未提交工作区；git diff --check通过（测试源码CRLF规范化提示不影响结果），清理dry-run JSON0／截图0，8000／5173无监听。本批未新增真实调用，3个正常原观测槽继续保留。新v12有限技术＋条件EV授权问题已提出，未收到答复前不执行。
