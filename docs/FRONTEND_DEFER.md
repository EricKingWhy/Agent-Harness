# 前端 DEFER 清单

> 按 AGENTS.md §8（Scope Lock）与 §5（工程规划边界）：发现但**不属当前批次 scope** 的问题
> 登记于此，只报告不改；落地需用户 / Primary Developer 确认后再开 ticket。

---

## F-DEFER-1 短列表搜索框并未真正隐藏（`.hidden` 没有 CSS 规则）— ✅ 已修复 2026-09-10

**发现于**：2026-09-09 code-review（`af0a270..88548af` 轮次），非该轮 diff 引入。

**现象**：`ModelPicker` / `ControlPicker` / `ContextProviderPicker` 都用

```tsx
className={`model-picker-search-wrap${entries.length > 5 ? '' : ' hidden'}`}
```

表达「≤5 条目录时隐藏搜索框」，但 `web/src` 下**没有任何 `.hidden` 规则**
（`grep -rn "\.hidden" web/src/` 零命中；`app.css` 只有 `.model-picker-search-wrap`
基础规则，无 `.hidden` 变体）。因此该类目前不产生任何样式效果——短目录下搜索框
仍然渲染，早前「短列表多余搜索框」的 UX 修复实际未生效。

**影响**：纯视觉 / UX 退化，无功能或数据影响。三个 picker 共用同一 class，一处修复即可。

**最小修复**：在 `web/src/styles/app.css` 的 `.model-picker-search-wrap` 附近加

```css
.model-picker-search-wrap.hidden {
  display: none;
}
```

**验证方式**：现有 e2e 对短目录的断言不涉及搜索框可见性，需补一条断言
（如 `expect(page.locator('.model-picker-search')).toBeHidden()`），或手工确认三个控件。

**风险**：低。注意 cmdk 要求 `CommandInput` 始终在 DOM 中——用 `display: none` 隐藏即可，
不要条件卸载组件。

### ✅ 修复记录（2026-09-10）

已加 CSS 规则（`web/src/styles/app.css`，`.model-picker-search-wrap` 基础规则之后），
并新增 e2e `web/e2e/picker-search-visibility.spec.ts`（5 条，长短目录 × ModelPicker /
ControlPicker / ContextProviderPicker）。负向验证：临时注释掉该 CSS 规则后，3 条短目录
用例立即失败，2 条长目录用例照常通过 → 断言确实锁住了行为。

**⚠ 修复暴露了 4 个既有 e2e 的坏断言**（此前因 CSS 缺失而「假通过」，一并修正）：

原因是 cmdk 把 `role="combobox"` 放在 `CommandInput` **本身**——搜索框 `display:none`
时该 role 也一起从 a11y 树消失，**且输入框拿不到焦点**（focus 落到浮层容器，
`page.keyboard.type` 静默无效）。因此：

- 「浮层是否打开」必须用 `[role="listbox"]`（`CommandList`，恒可见）判定，不能用 `combobox`；
- 要测搜索过滤，目录必须 >5 条（否则搜索框隐藏、输入无效）。

受影响并已修正：`e2e/model-picker.spec.ts`（改用长目录）、`e2e/control-row.spec.ts`
（拆出长目录过滤用例）、`e2e/context-providers.spec.ts`、`e2e/continuation.spec.ts`
（改用 listbox 判开）、`e2e/fixtures.ts`（helper 不再硬依赖 `combo.fill('')`）。
