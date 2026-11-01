# 缺省内容按业务修正检查

日期：2026-10-31。M15-EMPTY-02，HEAD33a6736及原未提交改动保留。用户纠正全站固定图标／问句的误用；本轮只调整公共内容契约、各模块图标／文案、规则和正式文档，不改助手显隐、业务命令、加载／错误保护、正文、数据或服务。

## 实际覆盖

EmptyState的icon:IconName和message:string为必传、无默认；RecordList的empty:EmptyStateContent也必传。所有生产及browser夹具随strict类型检查通过，避免遗漏调用方。复用现有Icon系统新增文档、建议、历史、版本和进展图标，无新依赖。完整业务内容及情形见[修正迭代](../../archive/iterations/v1.5/WALL-E.缺省内容按模块业务修正_V_1.5.md)。

源码逐个核对：工作台空／无匹配／页越界，文档目录与未选择、当前／历史空正文，大纲未选／无标题，AI起步，修改建议／待处理筛选，评论空／页越界／未选／历史限制，版本／运行记录空及页越界，进展主题／主线／依据。只有messages/timeline.tsx的AI起步保留“我们要构建什么？”，共享组件不含该文本。没有以空内容替代加载、失败、旧数据或恢复入口，简洁布局与原尺寸不改。

## 本轮检查

| 命令／方式 | 实际结果 |
| --- | --- |
| npm run typecheck | strict及未使用检查通过，所有新必传内容调用方已接入 |
| npm run format；npm run format:check | 锁定Prettier配置通过 |
| 一次性Vite middleware ssrLoadModule＋react-dom/server | 4种compact／fill组合分别传评论／文档内容，真实SVG不同、文案不同，均1图标＋1行、无交互元素；版本／运行记录透传各自内容，未读／加载／错误不误显示缺省，失败下保留旧行；finally关闭，无HTTP监听 |
| node --test tests/detail-layout.test.mjs tests/v15-directory.test.mjs | 17项通过，原新建后助手的可见／隐藏、页签／宽度保留、未知恢复及一次完成边界继续成立 |
| node frontend/node_modules/vite/bin/vite.js build --outDir 临时目录 | frontend内TemporaryDirectory，1268模块、957ms、退出0；只有原大chunk提示；上下文清理完成，不覆盖dist |
| 静态核对 | 35份相关Markdown／634个本地链接与锚点无缺失；旧规则替代提示与新归档齐全；FE摘要与当前断点一致、BE不变；临时入口0，git diff --check退出0 |

没有为文案新增镜像测试，没有重跑全前端440项或后端／真实供应方检查；旧报告的440／29等不当作本轮重跑。上轮浏览器连接超时，本轮没有重试或获取新视觉证据，实际页面几何／真实点击／多浏览器仍未验。本轮没有服务启停、测试JSON、截图、原始日志或Git提交。
