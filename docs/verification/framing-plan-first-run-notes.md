# 首次离线计划准备失败（保留）

首次执行 `.venv/Scripts/python.exe -X utf8 tools/framing-probe.py --prepare` 退出1。实际工具输出的失败位置为 framing_probe_cases.py 的 REVIEW 接受，断言 `INTERNAL_ERROR != GUIDE_ACCEPTED`。此前 ASK 取消夹具使用第10秒，随后复用的 REVIEW 接受辅助方法固定在第5秒，时间倒退，不代表生产时间契约应放宽。

修正夹具：全部接受/取消/历史检查结束和恢复使用严格递增的受控秒数；保持原实际命令、结果断言及配置不变。首次准备未到创建计划文件或任何Tokenization/Chat请求。此文件为工具输出的人工记录，不声称是完整原始stderr。后续自动化保留原始stdout/stderr及输入哈希。
