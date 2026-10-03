# 自动链接实际基线（2026-10-03）

D-004已批准CommonMark加GFM自动链接，不需要重新询问是否支持。此处记录差异，不改变批准资源或方言，也不把现有实现输出作为黄金预期。

正式依据：[GFM 6.9](https://github.github.com/gfm/#autolinks-extension-)。规则涉及URL起始边界、域名末段下划线限制、尾标点/括号/实体、邮件末字符，以及mailto/xmpp协议和xmpp资源范围。22个独立样例在shared/fixtures/autolink-v1.json，使用自行构造的example.test文本；这不是完整GFM一致性测试集。

本机原始证据：[实际结果](editor-browser-2026-10-03T13-14-26-317Z.json)。`passed=true`只表示采集完成，`conforms=false`明确表示语义未通过；命令输出BASELINE COLLECTED。真实Chromium/Crepe与真实后端分别运行同一组输入，19个输入文件前后hash一致，自身浏览器/Vite已关闭。

前端5处差异：email-tld-digit未生成链接；mailto-prefix、mailto-resource-excluded只给邮件部分生成链接；xmpp-prefix、xmpp-resource误用邮件链接且没有协议/资源完整范围。安装包micromark-extension-gfm-autolink-literal/dev/lib/syntax.js明确仍有协议/资源TODO，emailDomainAfter要求ASCII字母末字符。实际22例确认这些差异，不能只依包名判定支持。

后端16处差异：目前没有literal-autolink扩展（仅CommonMark角括号自动链接），所以www/https、各括号/实体/域名/邮件及协议例缺少链接；www-interior-markers同时将URL内星号按强调删除，纯文本变为`访问 www.example.test/abc.`，与黄金字面星号不同。6个排除/显式链接例正确，不是所有22例都失败。

下一单元应在生产parser与前端remark适配同时实现原始文本上的正式边界，再比较链接范围/href和完整纯文本。不能只在实体解码后的text token里做正则替换，不能在代码/已存在链接里生成嵌套链接，也不能让URL内强调标记先消失。后端4.2.0提供inline.ruler.before/at、StateInline.linkLevel/posMax和text terminator API；已读取实际安装源码。候选位置需按完整原始inline源缓存并控制扫描复杂度，避免每个字符重复向后扫描导致1M文本退化；posMax/linkLevel与转义/实体/链接标签上下文必须真实验证。frontend已经锁定的依赖保持不变，不先安装近似linkify库。

上述是修复前的历史事实。生产规则现已接入backend/app/documents/autolinks.py和frontend/src/documents/autolink-lexemes.ts、autolink-remark.ts，source-nodes移除整组默认GFM remark插件后重新装入已批准的表格/任务/删除线及新literal规则；保留serializer的自动链接转义，避免实体解码后的AST替换。协议大小写只按ASCII，Python忽略大小写不允许把长s等Unicode外观字符当HTTP协议。没有添加依赖或改冻结稿。

新增26独立上下文样例，包括表格header/body的实际chunk及尾标点、转义竖线、嵌套列表/引用/任务/标题、强/删除线、转义与实体不构造www前缀、URL内部实体字面保留、协议大小写、Unicode路径/emoji、ASCII与NBSP边界、无效域/未支持协议、图片/显式和引用链接/代码/HTML/CRLF。实体生成邮件全前缀与部分地址的语境没有足够独立规则证明，未把猜测登记为黄金值，此处限定为www实体前缀。Unicode域本身及更多括号标签语境仍待补，不能将这些样例宣称完整GFM一致性。

失败与修复：frontend-2026-10-03T13-40-54-898Z.json为插件this声明不兼容，修正为Milkdown接受的Processor类型；13-50-03表格没有链接，源行范围越过单元格实际EOF，修正为effects.check回滚探测chunk再消费最终边界；editor-browser-2026-10-03T13-58-09-664Z.json在Vite开发条件下探测consume前没有打开token，默认Node条件未暴露，已补探测enter/exit并新增development测试门禁。失败没有删断言或改已有22个黄金预期。

最新完整结果editor-browser-2026-10-03T14-08-31-198Z.json：48个预期一致，另3个段落/表格真实编辑输出保留链接原文；原15初始/15身份/19编辑行为/10实际键盘和输入门禁回归通过。真实后端接受并比较100对完整快照，29输入hash一致，测试会话/服务器关闭；仅隔离测试署名，不证明DB/HTTP保存。120后端、24前端与完整TS通过；额外4自动链接测试运行development条件，不重复计入独立测试数量。长无效候选/嵌套URL路径/链接标签测试控制重复扫描；后端文本终止搜索限于下一候选，前端使用该固定micromark版本的实际label stack而不反复遍历所有早期事件。没有残缺函数。下一单元补GFM单/双删除线、上述剩余链接/嵌套原始节点和完整组件。P3与373整体验收均未完成。
