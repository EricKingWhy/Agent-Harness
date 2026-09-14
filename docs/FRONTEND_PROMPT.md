# 前端 AI 提示词

后端 `feat/backend` 刚落地两个 commit（基于 `fefc31f`），其中 **commit 1 改了你消费的事件形状**，请同步评估前端兼容性：

## commit 1：`e8281d6` — inspect_artifact 字符级体积上限

**变更**：`inspect_artifact` 返回的 `ArtifactSlice.lines` 数组里，**超长行的字典新增两个可选字段**：

```ts
// 原形状（不变）
{ line_number: number, text: string }

// 单行超 2000 字符时（新）
{ line_number: number, text: string,  // text 已截断到前 2000 字符
  truncated: true,                    // 标记本行被字符截断
  full_length: number }               // 原始整行字符数
```

`ArtifactSlice.truncated`（顶层）语义也升级为「行数截断 ∪ 字符截断」的并集——任一发生即 `true`。

**你需要做什么**：
- TypeScript 类型 / Zod schema 把 `lines` item 放宽成 `truncated?` / `full_length?` 可选
- 工具卡片里渲染 `inspect_artifact` 结果时，单行 `truncated=true` 建议显示截断标记（如「⚠ 本行已截断，共 {full_length} 字符，可用 max_chars_per_line 放宽」），模型据此升级重读
- `inspect_artifact` 参数新增 `max_chars_per_line`（默认 2000，模型可放宽），前端若有参数编辑卡片需暴露

## commit 2：`95da7d9` — 集中事件映射（前端无感）

`to_agent_event()` 收敛了 11 处手拼 `AgentEvent`，**对外形状不变**，SSE 流字段全部保持。这次只是为未来加字段（如 `time` 透传）留单一入口，你这次不用动。

## 验收

- 后端 451 passed, ruff clean
- 前端建议跑一遍带 `inspect_artifact` 的事件回放回归
- 短片段（无超长行）的旧数据完全兼容——新增字段只在单行超 2000 字符时出现
