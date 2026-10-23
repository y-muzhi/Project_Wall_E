# 上下文 Token 一期：单次真实请求对照

时间：2026-10-18T18:28:15+08:00（Asia/Hong_Kong）。用户授权：发送一次真实请求测试Token节省。

独立历史快照观测；最多1次Tokenization批次＋1次Chat，无重试，不运行产品任务或采用返回。

```json
{
  "source_llm_use_id": 21,
  "source_request_sha256": "b4ff3275e71f8ff65aca57b4b5850ce979e2e806a2c45c21679b2337d884b7e6",
  "request_sha256": "bcb0853722b6e9df807b7fb3f74dc1dff5f7b994c18880566f516b6f8a086018",
  "model": "deepseek-v4-1-flash-260910",
  "old_actual_input": 125842,
  "old_actual_output": 3635,
  "old_cached": 65536,
  "blocks": 322,
  "history_messages": 10,
  "function": "INITIALIZE_REQUIREMENT@v9",
  "template": "new-requirement@v2",
  "old_characters": 305392,
  "new_characters": 118364,
  "maximum_count_batches": 1,
  "maximum_chat_attempts": 1,
  "maximum_output_tokens": 8192,
  "business_writes": false
}
```

计数批次1已准备；开始一次精确分词。
精确预检通过：六项[3769, 52174, 18, 2, 20452, 1565]；输入含1024余量=56967；计数请求ID=02179231929536958818742e03404164f2bdc6cf7ab386a9d6863。

Chat尝试1已准备；发送一次请求。该记录不是成功或收费证明。

## 实际结果

```json
{
  "actual_input_tokens": 55946,
  "actual_output_tokens": 1118,
  "actual_total_tokens": 57064,
  "cached_input_tokens": 0,
  "input_tokens_saved": 69896,
  "input_reduction_percent": 55.54,
  "old_total_tokens": 129477,
  "total_tokens_difference": 72413,
  "duration_ms": 19787,
  "finish_reason": "stop",
  "response_type": "INITIALIZE_CARDS",
  "chat_request_id": "02179231929642540d92d5266a85c14e28416df297f1b20ad409d",
  "observed_framing_delta": 3,
  "count_batches_invoked": 1,
  "chat_attempts_invoked": 1
}
```

对照使用调用21的同一归档正文、完整模板、历史和本轮输入；仅替换一期封装、定位索引与冻结Prompt。旧请求不重发。缓存计入输入，不重复加到合计；不同轮输出量和缓存状态不同，总量差及费用不可视为固定节省率。只有一次样本，不证明通用效果或供应方封装上界。


临时请求／响应JSON由TemporaryDirectory清理，仅留本Markdown摘要；未启动服务、未修改业务库或用户正文。

## 可读对照

|用量|旧调用21实际值|本次实际值|差值|
|---|---:|---:|---:|
|输入Token（含缓存部分）|125842|55946|减少69896，55.54%|
|输出Token|3635|1118|减少2517；两次回答内容不同|
|合计Token|129477|57064|减少72413；不是固定节省率|
|输入缓存命中Token|65536|0|缓存包含在输入内|

本次Chat耗时19787ms，finish_reason=stop，返回INITIALIZE_CARDS；未将候选写入需求，未执行事实采用或完整业务效果验收。两次缓存状态不同，不根据输入总Token降幅直接推断费用降幅。

|精确文本预检项|旧记录已保存计数|本次计数|
|---|---:|---:|
|System|3917|3769|
|完整User JSON|121922|52174|
|实际输入减去上述文本计数|3|3|

System减少148，User JSON减少69748，合计对应实际输入减少69896。此表前两项与实际消耗分开记录，预检使用原1024经验余量；本次观测实际差3，不将余量降至3或据一次样本改变准入。

为公平对照，本次保留归档调用21的new-requirement@v2原模板，而非换成当前新建模板v4；仅测试新Function v9封装与Prompt。系统新建目录和既有模板资源没有回退或改写。

收尾：项目测试清理工具执行完成，JSON=0、screenshots=0。首次本地执行在读取凭据及发送网络请求前遇到缺少tzdata的时区依赖，改为香港当前固定UTC+08:00后执行；该本地错误没有消耗计数／Chat槽。最终实际计数调用1、Chat调用1，无自动重试或额外请求。
