# 阶段确认与分析面板浏览器检查（2026-10-23）

环境：Chrome独立headless／Playwright CLI 0.1.22、真实FastAPI／SQLite／Worker、临时生产前端；Counter／Gateway为进程内私有离线依赖，真实API为0。使用Playwright技能，所有浏览器产物在临时目录，完成后清理，只保留本Markdown。

实际UI：新建需求，DISCUSS收到PHASE_CHANGE卡片，选择accept并确认；讨论进展从需求探索切至方案设计，卡片显示正式答案与阶段确认已保存。随后REVIEW可正确显示“检查”操作，正文保持V1。保存返回的Analysis可从文档记录→运行记录→具体检查运行→查看分析结果展开，实际显示分析完成、保存的摘要和覆盖材料d1v1；最终console Errors=0／Warnings=0。

离线夹具原REVIEW误用了不允许的NO_CHANGE结论，实际Schema诊断确认后改RESULT并携带实际文档引用；无效返回只展示原文，未写正文。早先将拒绝原因推断为coverage为空并不准确，本记录采用实际诊断。不是为了测试放宽产品校验。

新发现并定位的产品缺陷：单次model-call详情遇非空Wire recent_history时读取不存在的message_id，GET500；列表GET200。修复按同次ContextBasis.aliases.source_refs恢复真实MESSAGE／CARD_ANSWER ID、保序去重，不解析引用字符串猜ID，不调用编译／计数／模型。新增带实际历史的REVIEW及HTTP回归见test_v15_model_calls.py，最终结果续记于准入观测验证记录。新增测试初次错误假定历史ID1，实际文档创建动作ID2被携带，初始想法是长期来源；修正夹具断言，不改选材程序。

进程及清理：首个stdin EOF实例正常零IO退出；阶段槽PID50556／port59258／会话73064正常stop，离线计数2／Chat2；第二槽PID62704／port55186／48490计数1／Chat1；最终分析槽PID60596／port54097／64747计数1／Chat1。三个浏览器均close，临时目录5jwu7cj5、hhlv8l6_、_4fig6u7全部自动清理；未操作用户服务／库。最终分析正向槽通过实际HTTP建立隔离需求和目标、接受REVIEW，浏览器验证实际历史结果入口；不冒充全部由UI提交。

未覆盖：事实确认、评论／历史恢复全部浏览器路径、双标签竞争及完整布局组合；真实供应方及EV仍未执行。
