# V2.0基线与交付Git引用协议验证

日期：2026-11-05；BE0.17-draft-17，7.2.1及7.7.3—.7。代码为28a7c9e后的未提交V2工作区，无正常仓库／用户分支／索引／HEAD操作，无服务更新或付费调用。

## 实现

git_ref_protocol.py复用已有GitOID／对象格式及确定JSON；不可变RefPrepareInput只接受BASELINE_CREATE或DELIVERY_UPDATE。基线引用按原snapshot_id固定到refs/walle/baselines/<id>并只使用create；交付只接受完整refs/heads/*和当前对象格式的全长非零new／expected OID，禁止HEAD／短哈希／rev表达式、注入、自动规范化及任意引用命令。Delivery固定--no-deref --create-reflog -m WALLE:<delivery_id> --stdin -z，无--batch-updates。

prepare_bytes只含start、原create／update及prepare，COMMIT与ABORT是独立固定帧；不把提交预写到stdin。协议输入摘要仅覆盖该不可变输入，原repo／operation／step／nonce／程序及窗口绑定仍须实际调用方保存和校验。

RefAckDecoder有界分块读取原STDOUT的精确start: ok／prepare: ok／commit: ok或abort: ok及顺序；部分帧、额外输出、CRLF／未知文字／重复／非法阶段及容量超限均拒绝且不能重置成成功，结束时必须明确COMMIT或ABORT。退出0、EOF、旧值或已prepare不当commit ACK。stderr及其他进程输出不能转为该证据。

prepared_ref_observation要求真实查询exit_code为整数0、有界完整且唯一精确NUL字段；交付必须ref全名匹配、OID仍为expected且symref为空。基线仅在成功查询无匹配项时记录不存在；空失败输出不表示不存在。--no-deref不能单独防符号引用覆盖，持锁复核必须保留。

官方固定语法及事务阶段、名称规则已核对，且文档注明相应章节至2.56.0没有变化；实际兼容另由本轮固定Git验证。[update-ref官方文档](https://git-scm.com/docs/git-update-ref)、[check-ref-format官方文档](https://git-scm.com/docs/git-check-ref-format)。

## 实际检查

项目Python3.13.5／固定SQLite3.54.1／Ruff0.17.3，quality_python阻断外网并禁止正常数据／密钥读取。真实固定MinGit只在本轮新建sha1／sha256 bare库、独立worker与自有KILL_ON_JOB_CLOSE Job执行；没有生产Native命令放宽。

- 初始协议＋既有commit输入130通过，0.27秒；增加精确持锁查询后144通过，0.31秒，其中协议90、原提交payload54。
- 最终三文件test_content_manifest_git_vectors.py／test_git_ref_protocol.py／test_git_commit_input.py：145通过，6.69秒。包含实际固定Git全对象／配置向量与新增两格式引用事务，不是一次测试等同145次外部调用。
- 独立worker不导入产品协议代码，实际分阶段给原Git stdin发送prepare，读取真实start／prepare ACK，再运行原for-each-ref持锁观察后才发送commit或abort；真实全部stdout字节交产品decoder比较，实际prepare字节与产品compiler一致。
- 真实create-only基线保留及重复create拒绝；交付预期旧值冲突拒绝且ref未改变；prepare后abort释放且ref不变；正常commit后原目标为planned；reflog精确WALLE:31且明确固定测试committer／时间，不读取个人身份。
- 真实符号分支在--no-deref下能prepare：持锁观察仍为symref，产品验证器拒绝，worker实际abort后符号引用和原目标都保留。不能省略该复核。
- 实际固定Gitcheck-ref-format通过合法全名向量（含UTF8／层级／合法符号），产品不进行--branch扩展或--normalize。语法通过不是NTFS布局／路径能力证明。
- 新模块lint、181个backend/app格式及git diff --check通过。此前已验证的原生组件未机械全跑。既有httpx弃用提示保留。

原worker进程及全部Git孩子已退出、自有Job为空；所有新测试库／临时JSON／配置原始输出随专属根清理，只留此Markdown。

## 未覆盖／接续

组件没有执行Git、授予写权限或进行业务派发。仍需原资源Operation／Task的同一CodeOperationStep、可靠MAY_HAVE_BEEN_SENT与停止／代次／窗口栅栏、受鉴权Guard及完整固定Git登记、仓库／配置原身份、完整worktree／HEAD、原payload／对象闭包、私有追加GitReceipt及成功后核对、未知／ABA／真实中断恢复。

本轮没有模拟进程崩溃冒充真实故障，没有测试真实掉电或声称用户仓库跨程序冻结。生产Native仍只登记--version，runtime_admitted=false；不能据固定Git临时库事务通过声明REGISTER_BASE、交付或整个V2可用。
