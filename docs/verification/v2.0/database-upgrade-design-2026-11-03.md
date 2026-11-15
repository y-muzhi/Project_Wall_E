# V2.0 数据库保留升级设计静态核对

日期：2026-11-03（Asia/Hong_Kong）。类型：Markdown、源码及官方资料静态核对。Q20-DB／DB20-UPGRADE-1；后端0.10-draft-10／前端0.9-draft-9均DRAFT。

## 范围与基线

本单元修改7份V2.0 Markdown：[独立迭代](../../iterations/pending/v2.0/WALL-E.数据库保留升级与恢复迭代_V_2.0.md)、[后端](../../design/v2.0/WALL-E.后端设计文档_V_2.0.md)、[前端](../../design/v2.0/WALL-E.前端设计文档_V_2.0.md)、[设计断点](../../project/v2.0/设计进度_V_2.0.md)及两处索引和本记录。迭代先保存后同步DRAFT；前序检查迭代／记录及其他36份受保护文档未授权修改。HEAD基线8c5df4c6683e10c265e2f719a4fdc09ba4210ea0，用户和并行任务的V1.5前端／文档及EV20-01改动保留，不提交／推送／修改忽略。

读取源码而不连接数据库：database.py完整、ProcessLock完整，当前v1_5.sql的结构／LLMUse／metadata／序列／触发器相关段落；CountingJournal、CollaborationAdmission／Observation、service及审计读写／purge相关分支，全后端llm_uses查询位置；补读evidence_database完整版本分派和_saved／_suspended。首次命令含Windows不展开通配路径／不存在的候选文件，以及部分大输出截断，均重新定向真实路径并读取所需片段；未当成功读取或创建不存在文件。未全文审计SQLite／OS／全部审计实现，未查看真实业务库、配置秘密、进程和监听。

当前151 Schema原字节SHA256=9e99874afdf857cafb649ab378431dfd6c12ebda87ea486cb5df463300e74811；evidence_150=14b56e50d74eacba271e00441340a92d7338ccbab9eda06c1f2e8e67ac9f91d1；database.py=b7398f2964a5d4f7ee0364efd20d72c521d2d05ebae4bf6f10f417a7cdae48c9。本轮不生成200 SQL、发布清单、维护程序、数据库或备份。

## 设计结论及来源

DB20-UPGRADE-1区分最终200对象发布清单与真实执行历史，允许显式fresh或精确151升级；不改冻结旧SQL／checksum。保留全部旧列typed投影、ID／序列／状态、原路径及审计字节。Backup API及一致性核验后副本演练，正式apply在原路径单SQLite事务中完成；提交未知只核对原upgrade_id，200新写入后不以旧备份覆盖。

普通ProcessLock不等于任意外部SQLite写入隔离，实际维护须另获授权、退出所属活动／后端并关闭外部写入工具。前端只展示不可达／归属与原动作恢复，无维护控制台；原审计调用与purge需要显式document分支，代码不套GuideRun。

官方依据：[Backup API](https://sqlite.org/backup.html)用于一致备份而非只拷主文件；[WAL说明](https://sqlite.org/wal.html)用于sidecar边界及WAL-reset修复版本；[ALTER TABLE](https://sqlite.org/lang_altertable.html)用于建新表、复制、再改名的受控顺序；[PRAGMA](https://sqlite.org/pragma.html)用于事务外切换外键、完整性与外键分别检查。最低SQLite3.51.3只是设计准入下界，实际DLL／构建／能力未验证；本轮不升级环境或声称修复已落地。

## 命令和实际结果

- 只读源码定位：rg --files backend/app/infrastructure；rg -n 'check_schema|backup_to|MIGRATIONS|SCHEMA_VERSION' backend/app/infrastructure/database.py；rg -n 'FROM llm_uses|JOIN llm_uses|UPDATE llm_uses' backend/app --glob '*.py'；Get-Content用于以上实际文件相关段落。
- Python标准库只读静态脚本核对7份文档链接／围栏／表格／尾空白、八章、稳定定义、HTTP绑定、目标场景与当前版本；对保护文件及四组实际源码／资源计算SHA256；没有调用应用或sqlite3连接。临时写入使用同目录文件、flush／fsync／关闭、原字节并发核验及os.replace。
- Git只读rev-parse HEAD、diff --check；不运行Git协议写入／维护／提交。
- 最终静态核对通过：7份文档129处相对链接可达、20处外部资料引用、62个稳定定义均有定义、37个客户端读取／写入绑定均可映射；八章／目标场景唯一性／当前版本和前后端互引／表格／围栏／尾空白通过。后端92项、前端55项场景均未执行。
- 36份保护文件逐字节摘要未变化；四组758份源码／资源摘要均与本单元开始一致：backend/app 131份=9a3c01e989689f51e0f61868b8e75312032911020e6616ebb6c684208350baa0；backend/resources 356份=92621c442c58c79b11e7a7c3b5725632be26a8da6489cf6158f4d2bbfc818fea；frontend/src 150份=170613a17e82cf84f8ee5723dbee9e419d114b2e9641ea9e59fdbc99add85ed1；frontend/tests 121份=0e5891dd0124c158a5952bd663da3b4d4c2a6f4346832c23a6a7df224654657c。HEAD保持基线，git diff --check退出0，本轮同目录临时文件0。
- 人工交叉复核修正：明确空库无任何用户对象／迁移元数据；新业务表为空排除必要Schema元数据；code_schema_state不可变与旧历史分离；补evidence_database按150／151／200精确只读校验，原冻结证据不迁移；后端Q20-FE当前标签对齐前端0.9-draft-9，前端维护段落移回服务端事实职责。静态脚本初次未发现这些语义／标签遗漏，修正后扩充相应核对。
- 最终设计摘要：后端=8042c1946aa433fb3f71ac4ce38865d7b1b57748ebd0204e718532884d4c969d；前端=943f097239f05ee444010e5b40135b8ac067975b81557876b0b90ae36070589e；独立升级迭代=17736d2b51f55b26aefae193b1876e4873f88b1a6961f7a21662380c1906ac39。哈希仅用于本单元设计接续，不是SQL资源发布摘要或运行证据。

## 未执行与状态

后端TC20-01—92、前端TC-FE20-01—55均是设计目标，本单元执行0。未运行初始化、迁移、备份、演练、SQLite约束／并发／故障／断电专项、产品单元／集成／类型／格式／构建／浏览器、Windows／OpenCode／Git协议、真实模型或计数API。未安装／下载运行包、修改真实配置／数据／服务，未建立本轮产品进程。

八项技术设计已有明确方案；全部实际资源／SQL／代码和真实运行证据仍按各自缺口保留，Q20-FE仍DRAFT。设计已定不等于数据升级、存储就绪、软件完成或验收通过。正常业务备份／审计是未来产品恢复资产，不能套测试产物清理；本轮仅静态核对，无测试JSON、截图、录像、原始日志留存。
