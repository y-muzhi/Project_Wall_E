# V2.1第二轮真实结果定位（进行中）

日期：2026-11-18。实际分母、次数与结束状态以ai-admission-default-2026-11-18-v2.md为准。当前执行-02槽；不修改本轮源码、资源、清单或模型返回，不自动补发。

## 已确认样本

- EV21-BLANK-01-PATH：真实返回purpose=FORMATION_PATH_CHANGE，完整取消/成果/依赖方向已较前轮明确，但ADD_STEP.expected_results使用普通增量的temp_ref，而路线卡要求temp_result_ref。按该用途的Schema单支路校对，失败位置为action_payload.changes[0/1]的expected_results；C07正确拒绝，没有发布卡。
- EV21-BLANK-01-ASSOCIATE：formation_delta的ASSESS_STEP.document_refs填d42v2而非本轮真实区块别名；程序在ModelEvidence.block_ids拒绝。给出的source_refs中能看到真实d42v2b12/d42v2b13，但没有把它们放入document_refs。
- EV21-BLANK-01-ASSESS：空文档d42v1作为document_refs值，被只接受区块别名的覆盖校验拒绝；空文档没有区块时应使用空列表，并以真实当前消息等来源说明GAPS_REMAIN/UNCERTAIN。

设计依据是后端DTO-MODEL：ASSESS_STEP.document_refs为已发送区块别名[]，ASSOCIATE_CONTENT为当前真实区块别名非空；完整文档身份不等于该字段的区块集合。因此不通过自动展开全文/补点号/改写模型返回放行。

## 定位方式

固定SQLite先activate，只读打开本轮隔离正常DB；恢复原已计数context，运行progress/model/publication纯准备，不执行保存或任何供应方调用。路线卡额外按ModelCardGroup匹配purpose单支路检查字段路径，避免顶层oneOf安全错误隐藏具体字段；不更改该安全错误对用户的合同。

## 后续修复方向（尚未实施）

区分普通formation_delta ADD_STEP和路线卡ADD_STEP两套嵌套字段；提供精简、准确的两种形状说明。对document_refs在新资源Schema中声明区块别名类型/格式及复制本轮ref的约束，Prompt明确空文档用空列表，完整文档别名不可当覆盖块。只增强已有合同的说明及静态类型，不扩大模型读取/写入权限。新资源必须新增批次，不修改当前v29/v30，不能借当前冻结许可重试。
