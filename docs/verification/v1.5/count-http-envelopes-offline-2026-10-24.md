# V1.5计数错误结构兼容离线专项

2026-10-24。原11文件联合79 passed／24子场景／475.90秒通过后，真实新单次诊断仍HTTP400且NO_ERROR_OBJECT，暴露只识别嵌套error对象。扩展为选择已知错误说明字段：根message／Message／msg、detail文本或前5个验证错误、元数据Error，以及error文本；不把input等任意值折成说明。未知对象只保留≤20个安全字段名。原7字段私有记录仍可验证，新body_keys可选，30天边界和状态／身份保护保持。

命令：.venv/Scripts/python.exe -m pytest backend/tests/infrastructure/test_tokenization.py backend/tests/infrastructure/test_counting_journal.py backend/tests/guide/test_v15_count_probe.py -q -p no:cacheprovider。实际28 passed／24 subtests／83.19秒，1条既有提示；包括真实loopback不同错误结构和保留／脱敏／未知边界。其后仅在工具Markdown显示安全字段名，定向count_probe -k http_failure：1 passed／3 deselected／7.36秒。全为离线／私有响应，没有新真实IO。未机械重跑79项，不把原HTTP400改成原因已查明。

正式BE仅私有错误审计说明更新，SHA256=fe5ef57a1d1b9126600df10e044ddc8833e9ebf45fc39bd04eb2c1003cbae817。模型89类型／Prompt／计数定义／resources v13未变；manifest仍6ca926d0aa0954ec2dafc19225a7c65e21bdae1b6db99054667b6957436f8e2d。新工具SHA256=c8ed6c16d6c179cce40c8d2500d91945afd717c2d3168d4401b8fbc8d3983e98。
