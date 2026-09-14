/** ContextProviderPicker — Radix Popover + cmdk Command 实现的多选控件。
 *
 * 复用 ControlPicker / ModelPicker 的 Popover+cmdk Command 模式，差异：
 *   - 多选语义：onSelect 切换某条目的选中态，不关闭 popover（用户可连续勾选）；
 *   - trigger 显示选中数量（如「Context · 2」），未选时显示 placeholder；
 *   - 选中态暴露在 `role="option"` 的 `aria-selected` 上（FE-R11-06：辅助技术
 *     读不到画在 `aria-hidden` checkbox 上的勾选态，`aria-selected` 此前只表示
 *     cmdk 高亮）；
 *   - selectedIds 先与 entries 求交（FE-R11-07：否则会出现"已选但列表里没有、
 *     也取消不掉"的幽灵项，计数还多算）；
 *   - 空目录不渲染（不伪造列表）。
 *
 * 契约向后兼容：
 *   - class 名 `composer-control` 在 trigger 上（与 ControlPicker 同族）；
 *   - aria-label 由调用方传入；
 *   - 空目录不渲染任何节点。 */

import * as Popover from '@radix-ui/react-popover';
import { Command, CommandGroup, CommandInput, CommandItem, CommandList } from 'cmdk';
import { useMemo, useRef, useState } from 'react';
import { ChevronDown, Layers, type LucideIcon } from 'lucide-react';
import type { CatalogEntry } from '../lib/api';
import { focusPickerListOnOpen } from '../lib/pickerFocus';

interface Props {
  /** aria-label，也是 trigger title 的一部分。 */
  ariaLabel: string;
  /** 目录条目（来自 GET /api/context-providers）。空 → 返回 null（调用方隐藏入口）。 */
  entries: CatalogEntry[];
  /** 当前选中的 id 列表。空 = 未选。 */
  selectedIds: string[];
  /** 选中变更回调——传入新的完整 id 数组。 */
  onChange: (ids: string[]) => void;
  /** trigger 上显示的 icon。默认 Layers。 */
  icon?: LucideIcon;
  /** 未选中时 trigger 显示的 placeholder 文本。 */
  placeholder: string;
  disabled?: boolean;
}

export function ContextProviderPicker({
  ariaLabel,
  entries,
  selectedIds,
  onChange,
  icon: Icon = Layers,
  placeholder,
  disabled = false,
}: Props) {
  const [open, setOpen] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  // FE-R11-07：条目目录变化后，旧的 selectedIds 可能已经不在列表里——那样的 id
  // 既看不见也取消不掉，却还计入 trigger 的「Context · N」。渲染前与 entries 求交，
  // 让"能看到的"与"算进去的"永远是同一集合。
  const knownIds = useMemo(() => new Set(entries.map((e) => e.id)), [entries]);
  const effectiveIds = useMemo(
    () => selectedIds.filter((id) => knownIds.has(id)),
    [selectedIds, knownIds],
  );
  const selectedSet = useMemo(() => new Set(effectiveIds), [effectiveIds]);
  const count = effectiveIds.length;
  const triggerLabel = count > 0 ? `${placeholder} · ${count}` : placeholder;
  const searchHidden = entries.length <= 5; // 阈值与 picker-search-visibility 契约一致

  // 端点缺席：不渲染（不伪造列表）。调用方靠这个降级隐藏入口。
  if (entries.length === 0) return null;

  const toggle = (id: string) => {
    const next = new Set(effectiveIds); // 从"实际可见"的集合出发：幽灵 id 顺手清掉
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(Array.from(next));
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          className="composer-control"
          aria-label={ariaLabel}
          title={triggerLabel}
          aria-disabled={disabled || undefined}
          disabled={disabled}
        >
          <Icon size={13} className="composer-control-icon" aria-hidden="true" />
          <span className="composer-control-current">{triggerLabel}</span>
          <ChevronDown size={12} className="composer-control-chevron" aria-hidden="true" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="model-picker-content"
          side="top"
          align="start"
          sideOffset={6}
          // FE-R11-04：短目录搜索框不可见 → 焦点交给 listbox，键盘导航才有效
          onOpenAutoFocus={focusPickerListOnOpen(listRef, searchHidden)}
        >
          <Command
            label={ariaLabel}
            // 与 ControlPicker / ModelPicker 同款 includes 子串匹配。
            filter={(value, search, keywords) => {
              const q = search.trim().toLocaleLowerCase();
              if (!q) return 1;
              const haystack = [value, ...(keywords ?? [])].join(' ').toLocaleLowerCase();
              return haystack.includes(q) ? 1 : 0;
            }}
          >
            <div className={`model-picker-search-wrap${searchHidden ? ' hidden' : ''}`}>
              <Icon size={13} aria-hidden="true" />
              <CommandInput placeholder="搜索…" className="model-picker-search" />
            </div>
            {/* 多选列表：告诉 AT「这里的选中不是单选高亮」（FE-R11-06） */}
            <CommandList ref={listRef} aria-multiselectable="true">
              <CommandGroup>
                {entries.map((e) => {
                  const checked = selectedSet.has(e.id);
                  return (
                    <CommandItem
                      key={e.id}
                      value={e.id}
                      keywords={[e.display_name, e.description]}
                      className={`model-picker-item ${checked ? 'sel' : ''}`}
                      /* 勾选态挂在 option 上：cmdk 硬写 aria-selected（= 高亮，
                         不是勾选），aria-checked 它不碰，所以能落地。
                         里面的 ☑/☐ 只给看得见的人，故 aria-hidden。 */
                      aria-checked={checked}
                      // 多选：切换选中态，不关闭 popover。
                      onSelect={() => toggle(e.id)}
                    >
                      <span className="ctx-picker-checkbox" aria-hidden="true">
                        {checked ? '☑' : '☐'}
                      </span>
                      <span className="model-picker-item-label">{e.display_name}</span>
                      <span className="model-picker-item-meta">{e.description}</span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            </CommandList>
          </Command>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
