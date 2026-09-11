# 2026-09-08 真实 Claude L4：嵌套业务 JSON 被截断

## 结论

T811 修复 TaskOutput 宿主信封后，真实 Architect Worker 的结果继续暴露了下一层缺口：Worker 正文是带说明文字和 Markdown fenced block 的完整 JSON，业务对象内包含嵌套数组/对象。原解析器用非贪婪正则匹配第一个 `}`，把合法业务对象截成非法 JSON，导致 `HOST_WORKER_OUTPUT_INVALID`。

## 真实证据

- Claude Worker 已完成并写入私有 outcome。
- Hook 已将完成态 `task.output` 规范化为 `content[0].text`，不再泄漏 `retrieval_status/task`。
- Assembler 仍因嵌套业务 JSON 被截断而把该 Worker 归类为输出无效。
- Core 保留 active Architect Action，没有伪造成功；但模型误把失败理解为应重新规划/改写当前 Action，造成无效重试。

## 根因

`re.findall(r"\{.*?\}")` 只能处理无嵌套对象，无法识别 JSON 的括号层级、字符串转义和嵌套数组。它不应承担结构化协议解析职责。

## 修复边界

- 使用标准库 `JSONDecoder.raw_decode` 从文本中识别完整顶层 JSON 对象。
- 每次成功解析后跳过完整对象，嵌套对象不重复计数；正文中存在第二个顶层对象时仍拒绝，保持 fail-closed。
- 不递归解包任意 `result`、不从模型文本读取 Host handle/model/isolation，不改变 Assembler 的唯一事实合并边界。

## 验证

- 新增 `test_record_worker_outcome_parses_nested_json_business_object`，覆盖说明文字 + fenced JSON + 嵌套对象。
- 保留多层 Codex `result` 包装拒绝回归，确保兼容性修复不会退化成宽松解析。
