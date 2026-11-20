# V2.1前后端详细设计输出静态核对

日期：2026-11-14（Asia/Hong_Kong；2026-11-13开始编写）。工作区codex/v2.1-design-review，HEAD21651c338ef3546c39a65526ed53c24653f30c77。范围仅详细文档及只读来源核实，无产品执行。

交付：[后端详细设计](../../iterations/pending/v2.1/WALL-E.后端设计文档_V_2.1.md)、[前端详细设计](../../iterations/pending/v2.1/WALL-E.前端设计文档_V_2.1.md)，均0.1-draft-1／DRAFT，八章＋附录，保留pending；源输入大纲0.12未修改。已同步计划、映射、索引及[当前断点](../../project/v2.1/实现进度_V_2.1.md)。没有正式合并或升级EFFECTIVE。

## 实际检查与结果

使用PowerShell中的Python内存脚本静态核对，未保存测试脚本／JSON报告／原始日志；文件保存采用同目录临时文件、flush/fsync、并发原字节比较及os.replace，成功／失败清理临时文件。

| 范围／方法 | 实际结果 |
| --- | --- |
| 模板条目：标题解析及人工职责核对 | 两份均1—8章；后端8组对象／9能力，前端3组对象／7能力；各对象3.1—3.5、能力4.1—4.5及4.8齐全；查询／AI条件条目在负责能力填写，前端复用后端AI规则 |
| 接口／字段／共同边界静态交叉阅读 | 修正实际conversation-messages responses路径、原五字段回答body、原九字段创建运行body、success/error封装与meta.pagination；保留原字段，不冒充已有新功能 |
| 状态与命令联合解析 | 15种原生命令、14类PathChange、12类AI变化；RETURN_FROM_BRANCH、enter_after_resume及恢复事件依据一致；双OPEN归属／一次消费／非当前节点焦点边界写入对应能力与UI |
| 模型与来源 | Wire实际八根、八计数文本对齐collaboration_context；source别名与Canonical真实引用分离；CARD_RESPONSE仍为新增目标；新release未发布，旧v5未采用 |
| 需求覆盖 | TC-FORM-A01—A76连续唯一，预期逐条与大纲0.12完全一致，补充可重建FBASE／FGROW／并发／回滚夹具及操作；前端14项浏览器场景均标未执行 |
| Markdown表格／JSON／锚点 | 新两份107个表格列数一致；重复显式锚点为0；本轮新JSON示例可解析；内部相对文件／片段链接检查通过，共37份Markdown、234条相对链接（含4条片段链接） |
| 源字节保护 | 大纲SHA256保持3774e919a16cd09e18a548ee06227836f73cddea64fe1c89ea516caa441ff6a1；八份来源摘要逐一一致；不修改既有设计来源以免破坏冻结输入 |
| Git边界 | git diff --check退出0；git diff --name-only HEAD -- backend frontend resources docs/design docs/templates为空，无已跟踪产品代码／资源／正式设计／模板改动；旧验证正文不改 |

细化范围：目标实体／关系／历史19张表的字段／键／索引与事务、精确内容及路线采用、私有相关basis、分页同快照／历史高水位、Closure逐项事实、正常讨论复核、程序匹配与AI充分性分离、单次容量、旧资源／显式升级和前端存储恢复。新增DTO／Schema数值发布／源兼容尚有实施输入，不用静态通过替代执行证据。

## 来源及本轮限制

[来源核对](detailed-design-baseline-read-2026-11-14.md)保留当前文件与原工作区V2.0相关只读摘要、已读／未读范围。原工作区Git查询受到文件访问边界拒绝；未取得准确源提交／未提交清单，没有升级权限，不编造全量兼容。已经能读取的设计／代码／db20-r48文件支持本轮详细设计，发布仍须固定完整源manifest。

未执行：产品代码修改、目标可执行Schema／完整DDL／新资源生成或准入、业务库读写、迁移、依赖安装、类型／格式／构建／产品专项、浏览器／性能、模型／计数、服务启停／探测、Git提交推送。60样本模型评测与性能目标均为计划，没有本轮通过结论。

结论：完整前后端详细设计初稿及本轮静态核对完成，待后续审定；产品未实施／未验收。当前没有新产品需求未决项；真实V2.0全量源、可执行协议／DDL／资源／decoder与产品证据按T21继续接续。

文档摘要：后端`738e21dc4e21a30a412fc0977b6672dba007501c4bebd30d506637bfcec86c93`；前端`4e276d952b688ff73142fad73da6f5a06fca3cbf3fe793acce0e397d3af7d427`。
