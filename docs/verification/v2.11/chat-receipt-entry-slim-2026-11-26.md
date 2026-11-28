# V2.11 对话回执入口精简验收

2026-11-26（香港时间）。依据[独立迭代](../../iterations/pending/v2.11/WALL-E.对话回执运行详情入口精简迭代_V_2.11.md)，工作树 `codex/v211-receipt-followup`，基线 `fd484f4`。

- 前端格式、严格类型、生产构建和 656 项离线检查通过。回执按钮和专用弹窗代码已移除。
- 在独立 Edge 的候选版和已发布 8001 实测，展开实际文档 17 的「首次出稿」及「文档修改建议」，两个回执都无「查看运行详情」。仍可打开 V2、比对 V1 与 V2、打开模型请求详情，以及在 780px 单栏进入实际 3 组、13 条建议。浏览器未发起写请求或出现页面错误。
- 8001 仅切换静态入口，后端 PID 51052。主资源 `assets/index-Bcj8Qw7v.js`，HTML SHA-256 为 `95d94306abcfb0a5aff99d94ffe6b6db962ee28e2a3de8fd8c4783cbbe13363d`。旧入口保存在 `data/service-runtime-v211-review-20261125/frontend-chat-receipt-slim-2026-11-26/previous-index.html`。未调用模型或计数。
