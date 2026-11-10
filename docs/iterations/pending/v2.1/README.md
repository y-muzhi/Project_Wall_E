# V2.1待合并迭代

任务M21-FORMATION-01；当前修订0.9／DRAFT。当前设计依据为R01—R08与接入Schema v4：R01—R07规则已确认，R08支线原则已确认、模型判定机制为技术设计；Q03成果复核体验与Q04容量达限体验仍待评审。产品未实现、未验收，尚未合入正式规格。

## 当前设计入口

1. [设计总览](WALL-E.文档形成主线设计总览_V_2.1.md)：目标、用户旅程、事实边界与阅读顺序。
2. [主设计](WALL-E.文档形成主线与阶段性写入_V_2.1.md)：业务对象、数据流、AI与程序责任、存储和资源方案。
3. [交互与接入设计](WALL-E.文档形成主线交互与接入收口_V_2.1.md)：当前交互、接口／字段责任、并发／失败恢复与实施前置。
4. [实施契约与验收清单](WALL-E.文档形成主线实施契约与验收清单_V_2.1.md)：当前契约、不变量和A01—A60未来场景，均未执行产品验收。
5. [当前接入Schema v4](schemas/formation-integration.v4.schema.json)：192个定义／13根DTO；NativeRequest为14种变体，PathChange为13种；私有binding仍为formation_card_binding_v3。仅结构设计输入，尚未接入产品。
6. [整体评审记录R01—R08](WALL-E.文档形成主线整体评审记录_V_2.1.md)：用户决定及其来源；各轮过程描述不作为新的实施或发布授权。

[路线节点原型](previews/formation-route-v04.html)仅展示已认可的整体视觉方向，无真实业务连接；当前行为以设计正文为准。[项目计划与当前断点](../../../project/v2.1/README.md)记录实施边界及接续事项。

## 保留的历史结构输入

[核心Schema v1](schemas/formation-contract.v1.schema.json)、接入[Schema v1](schemas/formation-integration.v1.schema.json)／[v2](schemas/formation-integration.v2.schema.json)／[v3](schemas/formation-integration.v3.schema.json)保留原字节用于追溯，不与当前v4混用。历史检查只证明当时范围，不替代当前产品验证。
