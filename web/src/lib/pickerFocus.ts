/** Picker 浮层打开时的初始焦点（FE-R11-04）。
 *
 *  三个 picker（ModelPicker / ControlPicker / ContextProviderPicker）共用
 *  Radix Popover + cmdk Command。cmdk 把方向键 / Home / End / Enter 的处理挂在
 *  `[cmdk-root]` div 的 `onKeyDown` 上（`node_modules/cmdk/dist/index.mjs`），
 *  而这些**只能靠冒泡到达**——焦点必须落在 root 内部。
 *
 *  短目录时搜索框带 `.hidden`（`picker-search-visibility` 的 display:none 契约），
 *  于是 root 里没有任何可聚焦元素 → Radix 把初始焦点放到 Content 上，
 *  事件到不了 root → **纯键盘用户完全选不动条目**（方向键无反应、Enter 不提交），
 *  而鼠标路径一切正常，所以这个洞很容易漏掉。
 *
 *  修法：搜索框不可见时把初始焦点交给 listbox 自身（cmdk 的 `CommandList` 自带
 *  `tabIndex=-1` 且在 root 内，`aria-activedescendant` 也挂在它上面，正是
 *  「无输入框 listbox」的标准焦点位）。搜索框在场时保持 Radix 默认——
 *  焦点落搜索框，用户可直接输入过滤。 */

/** 给 `Popover.Content` 的 `onOpenAutoFocus` 用。 */
export function focusPickerListOnOpen(
  listRef: { current: HTMLElement | null },
  searchHidden: boolean,
): (event: Event) => void {
  return (event) => {
    if (!searchHidden) return;
    event.preventDefault();
    listRef.current?.focus();
  };
}
