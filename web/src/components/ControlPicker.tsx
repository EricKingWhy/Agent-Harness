/** ControlPicker — Radix Popover + cmdk Command 实现的通用单选控件。
 *
 * 复用 ModelPicker 的 Popover+cmdk Command 模式，用于 Composer control row 的
 * Permission Mode / Agent Profile / Reasoning Effort 三个单选控件。
 *
 * 与 ModelPicker 的差异：
 *   - 数据源是 CatalogEntry（{id, display_name, description}），不是 ModelCatalogEntry；
 *   - 没有 provider 分组——清单短，扁平展示即可；
 *   - 首项是「默认（未选）」：单选控件必须能回到"没选"，
 *     否则选了就再也退不回来（只能整页 reload），见 FE-R11-05；
 *   - trigger 显示 display_name，不是 id。
 *
 * 契约向后兼容：
 *   - class 名 `composer-control` 在 trigger 上；
 *   - aria-label 由调用方传入；
 *   - 空目录不渲染任何节点。 */

import * as Popover from '@radix-ui/react-popover';
import { Command, CommandGroup, CommandInput, CommandItem, CommandList } from 'cmdk';
import { useMemo, useRef, useState } from 'react';
import { Check, ChevronDown, type LucideIcon } from 'lucide-react';
import type { CatalogEntry } from '../lib/api';
import { focusPickerListOnOpen } from '../lib/pickerFocus';

interface Props {
  /** aria-label，也是 trigger title 的一部分。 */
  ariaLabel: string;
  /** 目录条目（来自端点）。空 → 返回 null（调用方隐藏入口）。 */
  entries: CatalogEntry[];
  /** 当前选中 id（null = 未选/默认）。 */
  selectedId: string | null;
  /** 选中回调；null 表示选了「默认」或取消选中。 */
  onChange: (id: string | null) => void;
  /** trigger 上显示的 icon。 */
  icon: LucideIcon;
  /** 未选中时 trigger 显示的 placeholder 文本。 */
  placeholder: string;
  disabled?: boolean;
}

/** cmdk Item value 必须唯一、稳定（不依赖 textContent）。null 选中态用 sentinel。 */
const DEFAULT_VALUE = '__default__';

export function ControlPicker({
  ariaLabel,
  entries,
  selectedId,
  onChange,
  icon: Icon,
  placeholder,
  disabled = false,
}: Props) {
  const [open, setOpen] = useState(false);
  const selectedEntry = useMemo(
    () => (selectedId ? entries.find((e) => e.id === selectedId) ?? null : null),
    [entries, selectedId],
  );
  const triggerLabel = selectedEntry?.display_name ?? placeholder;
  const searchHidden = entries.length <= 5; // 阈值与 picker-search-visibility 契约一致（不因新增默认项而改）
  const listRef = useRef<HTMLDivElement>(null);

  // 端点缺席：不渲染（不伪造列表）。调用方靠这个降级隐藏入口。
  if (entries.length === 0) return null;

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
            // 与 ModelPicker 同款 includes 子串匹配（cmdk 默认 command-score 行为不一致）。
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
            <CommandList ref={listRef}>
              <CommandGroup>
                {/* FE-R11-05：单选控件必须能回到「没选」——否则选了就再也退不回来
                    （只能整页 reload）。提交 null，与 trigger placeholder 同义。 */}
                <CommandItem
                  value={DEFAULT_VALUE}
                  keywords={['默认', '未选', 'default', 'none']}
                  className={`model-picker-item ${selectedId === null ? 'sel' : ''}`}
                  onSelect={() => {
                    onChange(null);
                    setOpen(false);
                  }}
                >
                  <span className="model-picker-item-label">默认（未选）</span>
                  <span className="model-picker-item-meta">用后端默认值</span>
                  {selectedId === null && <Check size={13} className="model-picker-check" aria-hidden="true" />}
                </CommandItem>
                {entries.map((e) => (
                  <CommandItem
                    key={e.id}
                    value={e.id}
                    keywords={[e.display_name, e.description]}
                    className={`model-picker-item ${selectedId === e.id ? 'sel' : ''}`}
                    onSelect={(value) => {
                      onChange(value);
                      setOpen(false);
                    }}
                  >
                    <span className="model-picker-item-label">{e.display_name}</span>
                    <span className="model-picker-item-meta">{e.description}</span>
                    {selectedId === e.id && <Check size={13} className="model-picker-check" aria-hidden="true" />}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
