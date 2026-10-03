# 自动链接实际基线（2026-10-03）

D-004已批准CommonMark加GFM自动链接，不需要重新询问是否支持。此处记录差异，不改变批准资源或方言，也不把现有实现输出作为黄金预期。

正式依据：[GFM 6.9](https://github.github.com/gfm/#autolinks-extension-)。规则涉及URL起始边界、域名末段下划线限制、尾标点/括号/实体、邮件末字符，以及mailto/xmpp协议和xmpp资源范围。22个独立样例在shared/fixtures/autolink-v1.json，使用自行构造的example.test文本；这不是完整GFM一致性测试集。

本机原始证据：[实际结果](editor-browser-2026-10-03T13-14-26-317Z.json)。`passed=true`只表示采集完成，`conforms=false`明确表示语义未通过；命令输出BASELINE COLLECTED。真实Chromium/Crepe与真实后端分别运行同一组输入，19个输入文件前后hash一致，自身浏览器/Vite已关闭。

前端5处差异：email-tld-digit未生成链接；mailto-prefix、mailto-resource-excluded只给邮件部分生成链接；xmpp-prefix、xmpp-resource误用邮件链接且没有协议/资源完整范围。安装包micromark-extension-gfm-autolink-literal/dev/lib/syntax.js明确仍有协议/资源TODO，emailDomainAfter要求ASCII字母末字符。实际22例确认这些差异，不能只依包名判定支持。

后端16处差异：目前没有literal-autolink扩展（仅CommonMark角括号自动链接），所以www/https、各括号/实体/域名/邮件及协议例缺少链接；www-interior-markers同时将URL内星号按强调删除，纯文本变为`访问 www.example.test/abc.`，与黄金字面星号不同。6个排除/显式链接例正确，不是所有22例都失败。

下一单元应在生产parser与前端remark适配同时实现原始文本上的正式边界，再比较链接范围/href和完整纯文本。不能只在实体解码后的text token里做正则替换，不能在代码/已存在链接里生成嵌套链接，也不能让URL内强调标记先消失。后端4.2.0提供inline.ruler.before/at、StateInline.linkLevel/posMax和text terminator API；已读取实际安装源码。候选位置需按完整原始inline源缓存并控制扫描复杂度，避免每个字符重复向后扫描导致1M文本退化；posMax/linkLevel与转义/实体/链接标签上下文必须真实验证。frontend已经锁定的依赖保持不变，不先安装近似linkify库。

生产修复尚未开始；没有残缺的生产函数。两端基线辅助函数均完整运行。下一次从自动链接生产规则开始，扩充大小写、Unicode域/边界、转义、实体、嵌套容器/表格、图片和长文本，再执行原49对快照回归。P3、完整编辑器和373整体验收均未完成。
