# V2.0实施枚举绑定补充

日期：2026-11-04；状态：PENDING／用户已确认按建议实施；未合入两份设计。

## 来源与缺口

BE 0.17-draft-17的ModelPriceVersion.channel与NativePermission.requested_action标为枚举，但字段所在章节未列取值；渠道正文仅固定现有北京渠道，权限正文要求规范化原动作、对象不明不得ALLOW_ONCE。实施构造器对此原先明确拒绝，未用任意字符串假装枚举闭合。

本轮先集中询问并依通用实施授权采用可调整默认继续其余构建；用户随后明确回复“按建议实施”（2026-11-04），确认下列取值与UNKNOWN禁止授权规则。确认不扩展真实调用、服务或正常数据操作许可；独立迭代仍待明确合并。

## 本轮实现约定

- channel唯一值ARK_CN_BEIJING，引用现有model_profile中的ark.cn-beijing.volces.com渠道。它是本地不可变价格资源的渠道身份，不代表已发布或核验任何账户价格，不添加渠道选择或供应商。
- requested_action为READ／WRITE／EXECUTE／NETWORK／UNKNOWN。原工具名、patterns及metadata照常保存来源；动作及object_refs由适配器规范化，不能仅按这个标签授予权限。无法核对对象或动作归一为UNKNOWN，禁止ALLOW_ONCE，仍可明确拒绝或核对。
- 不能把UNKNOWN或缺失映射为EXECUTE／WRITE，也不按用户自然语言直接增加授权。此规则约束后续原生适配及APP-CODE-QUESTIONS实际调用，当前仅完成数据库枚举约束。
- 读写／取消／停止及现有文档业务不变；程序保护仍按真实对象、当前owner、代次、原权限请求及配置子集执行。

## 影响与验证边界

影响Schema200列约束、原生权限归一及未来对应HTTP decoder。独立迭代保留pending；当前设计hash／DRAFT状态不改。现有渠道URL来自项目源码，只做静态引用，不网络访问、不读取密钥、不创建价格或真实调用。数据库结构专项不代表权限适配、供应方或Windows隔离验收通过。
