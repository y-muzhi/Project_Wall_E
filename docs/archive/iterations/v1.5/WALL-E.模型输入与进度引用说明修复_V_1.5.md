# WALL-E 模型输入与进度引用说明修复 V1.5

2026-10-23。依据正式BE AI-RESOURCE去重及引用规则和独立实际观测，不放宽程序权限或替模型改写返回。

## 事件及最终规则

v10真实计数及Chat通过技术准入：S6764／U342，实际输入7109，framing gap3；但模型将goal_and_decisions的text=null视为缺失输入，并使用t-value／e-m1等自造临时引用，topic.evidence_refs填消息m1。实际delta被ADD临时引用保护拒绝，pending保留。技术准入和业务效果必须分开。

已有规则只在程序／设计的语义章节中，实际五段common_prompt和宽Ref Schema未把去重及交叉引用约定告知模型。修复将确定说明并入正式Prompt第三／四段：null通过ref读取本轮或其他已携带原文；自由文本和正式回答来源；basis_ref原样返回；ADD new_tN／new_eN、UPDATE真实当前主题；主题evidence_refs只引用依据，消息引用用于source_refs；pending ID及无可靠增量null。沿用89类型、六输出、四阶段及所有事务／来源保护，不添加输出修复或新调用。

## 实现及发布

新追加backend/resources/v11，Prompt v3／release v3，21文件；默认catalog切换v11，冻结v9／v10不变。manifest=db892fff3c7570ee94c1d2980f1424f50152e33125f604f80073a0f1ce35f86e；release=d7f67c022e1276b21b2628e93f2de76c467ba5caacdb59ac35dc99b2807b4872。生成来源BE SHA256=de47073e2dc7294831aa016a9e0d4ce840900da7bfb720dc3977efc75b7de307。

v11保持OFFLINE_READY；v10实际LIVE_VERIFIED证据只能证明原release，不能授给新Prompt。两个正常独占槽及原失败均保留，许可已消耗，未执行新版本真实调用、EV或导入用户库。

## 检查与边界

资源专项补正式五段Prompt字节一致性；进度专项补任意t-value与消息充当依据ID的失败保持不变。完整24文件161 passed／577.21秒（1条既有提示），见verification/v1.5/offline-suite-2026-10-23-174202-726729.md。不用静态文本或Mock证明模型理解已修复，不重写真实样本为成功。

当前v11默认离线观测预览通过：system SHA256=25930b5be341785ca54125bd2f2939bb0e6e8fc3ce3e12096579bc31ba4bec4f、user SHA256=fa7dfd14b9cb14bc33c876b3065737fd91cac92a00be7276708317c99107bcdc，system22556／user1114码点；计数0、Chat0，完整预算保持。git diff --check及产物清理dry-run通过（JSON0／截图0）。
