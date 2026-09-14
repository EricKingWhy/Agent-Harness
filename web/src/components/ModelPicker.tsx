/** ModelPicker — Radix Popover + cmdk Command 实现的模型选择器（Phase 2a / F2）。
 *
 * 历史：Phase 2a 用 Radix DropdownMenu（`role="menu"`）——可用但语义不准，
 * menu 是动作菜单，不是可搜索的选项列表。F2 升级为 Popover + cmdk Command：
 *   - cmdk 注入 `role="listbox"`（List）、`role="combobox"`（Input）、
 *     `role="option"`（Item），匹配 SDD §11「Combobox/Command-like」；
 *   - 方向键 / Home / End / Enter 由 cmdk 内置，**但前提是焦点在 `[cmdk-root]`
 *     内部**（它的 onKeyDown 只能靠冒泡到达）——短目录时搜索框 display:none，
 *     焦点必须显式交给 listbox，否则方向键/Enter 全哑（FE-R11-04，
 *     见 `lib/pickerFocus.ts`）；
 *   - 搜索过滤走 cmdk 的 command-score（同时匹配 name/provider/model），
 *     通过 keywords 字段把 provider 和 model 也纳入打分；
 *   - Radix Popover 负责 portal 定位 + 外点关闭 + Esc 关闭（与 DropdownMenu 等价）。
 *
 * 「默认链」永远在顶部（null 提交）；分组按 provider；空目录 → 返回 null
 * （调用方据此隐藏入口，不伪造列表）。
 *
 * 契约向后兼容（ModelPicker.test.tsx 的 SSR 断言）：
 *   - class 名 `composer-model` 仍在 trigger 上；
 *   - `aria-label="模型选择"`；
 *   - 空目录不渲染任何节点；
 *   - 端点缺席时 trigger 文本为「默认链」。
 *
 * 数据真相仍是 /api/models（lib/api.ts 的 ModelCatalogEntry）。
 * 这里只提交偏好，不是会话内模型真相——后者仍以模型卡 data.model 为准（不变量 #22）。 */

import * as Popover from '@radix-ui/react-popover';
import { Command, CommandGroup, CommandInput, CommandItem, CommandList } from 'cmdk';
import { useCallback, useMemo, useRef, useState } from 'react';
import { Check, ChevronDown, Cpu, Search } from 'lucide-react';
import type { ModelCatalogEntry } from '../lib/api';
import { focusPickerListOnOpen } from '../lib/pickerFocus';

interface Props {
  models: ModelCatalogEntry[];
  selectedModel: string | null;
  onModelChange: (name: string | null) => void;
  disabled?: boolean;
}

/** 按 provider 分组（null/空 → 「其他」组）。Map 保留插入序。 */
function groupByProvider(models: ModelCatalogEntry[]): { provider: string; items: ModelCatalogEntry[] }[] {
  const groups = new Map<string, ModelCatalogEntry[]>();
  for (const m of models) {
    const key = m.provider && m.provider.length > 0 ? m.provider : '其他';
    const arr = groups.get(key) ?? [];
    arr.push(m);
    groups.set(key, arr);
  }
  return Array.from(groups, ([provider, items]) => ({ provider, items }));
}

/** cmdk Item value 必须唯一、稳定（不依赖 textContent）。null 选中态用 sentinel。 */
const DEFAULT_VALUE = '__default__';

export function ModelPicker({ models, selectedModel, onModelChange, disabled = false }: Props) {
  // Popover 受控开关：搜索框聚焦、键盘导航都由 cmdk 自己管，这里只管开/关浮层。
  const [open, setOpen] = useState(false);
  const grouped = useMemo(() => groupByProvider(models), [models]);
  const selectedEntry = useMemo(
    () => (selectedModel ? models.find((m) => m.name === selectedModel) ?? null : null),
    [models, selectedModel],
  );
  const effectiveSelectedModel = selectedEntry?.name ?? null;
  const triggerLabel = selectedEntry?.name ?? '默认链';
  // 默认链算一条（阈值与 CSS 契约 picker-search-visibility 一致）
  const searchHidden = models.length + 1 <= 5;
  const listRef = useRef<HTMLDivElement>(null);

  /** BUG-011：**弹层已关就不再接受选中**。
   *
   * 第一次选中后 `setOpen(false)`，但浮层在 `--dur-out`（150ms）退出动画期间节点
   * 仍留在 DOM 且可命中——真机上人类双击的第二次 `click`（实测间隔 ≤120ms 都会
   * 命中）会再次进入 `onSelect`，发出第二个 `POST /model`；后端两个请求各自基于
   * 同一份快照取号，写出重复 `seq`，该会话此后恒 404。
   * 关闭态下的选中一律丢弃——实测 `dblclick()`（一次手势两下点击）与
   * `page.mouse.click` ×2 都只产生一个请求：两次 click 之间 React 已提交
   * `open=false`，第二次进来必然看到关闭态。回归锁见 e2e/q-model-dedupe.spec.ts。 */
  const commitSelection = useCallback(
    (value: string) => {
      if (!open) return;
      onModelChange(value === DEFAULT_VALUE ? null : value);
      setOpen(false);
    },
    [open, onModelChange],
  );

  // 端点缺席：不渲染（不伪造列表）。调用方靠这个降级隐藏入口。
  if (models.length === 0) return null;

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          className="composer-model model-picker"
          aria-label="模型选择"
          title={triggerLabel}
          // Radix Popover 会注入 aria-haspopup/aria-expanded；aria-disabled 让 SSR 可见
          aria-disabled={disabled || undefined}
          disabled={disabled}
        >
          <Cpu size={13} className="model-picker-icon" aria-hidden="true" />
          <span className="model-picker-current">{triggerLabel}</span>
          <ChevronDown size={12} className="model-picker-chevron" aria-hidden="true" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="model-picker-content"
          side="top"
          align="end"
          sideOffset={6}
          // FE-R11-04：短目录搜索框不可见 → 焦点交给 listbox，键盘导航才有效
          onOpenAutoFocus={focusPickerListOnOpen(listRef, searchHidden)}
          // 高度上限 + 滚动由 CSS 处理（避免目录长时顶出视口）
        >
          <Command
            label="模型选择"
            // cmdk 默认 filter 走 command-score；我们用简单 includes 兼容旧「子串匹配」预期，
            // 同时把 provider/model 也喂进 keywords 提升多字段命中率（输入「anthropic」能匹配到 claude-sonnet-4）。
            filter={(value, search, keywords) => {
              const q = search.trim().toLocaleLowerCase();
              if (!q) return 1;
              const haystack = [value, ...(keywords ?? [])].join(' ').toLocaleLowerCase();
              return haystack.includes(q) ? 1 : 0;
            }}
          >
            <div className={`model-picker-search-wrap${searchHidden ? ' hidden' : ''}`}>
              <Search size={13} aria-hidden="true" />
              <CommandInput placeholder="搜索模型" className="model-picker-search" />
            </div>
            <CommandList ref={listRef}>
              {/* 默认链永远在顶部（null 提交——后端按默认链行为） */}
              <CommandGroup>
                <CommandItem
                  value={DEFAULT_VALUE}
                  className={`model-picker-item ${effectiveSelectedModel === null ? 'sel' : ''}`}
                  onSelect={commitSelection}
                >
                  <span className="model-picker-item-label">默认链</span>
                  <span className="model-picker-item-meta">系统自动选</span>
                  {effectiveSelectedModel === null && <Check size={13} className="model-picker-check" aria-hidden="true" />}
                </CommandItem>
              </CommandGroup>
              {grouped.map(({ provider, items }) => (
                <CommandGroup key={provider} heading={provider}>
                  {items.map((m) => (
                    <CommandItem
                      key={m.name}
                      value={m.name}
                      keywords={[m.provider, m.model].filter((s): s is string => Boolean(s?.length))}
                      className={`model-picker-item ${effectiveSelectedModel === m.name ? 'sel' : ''}`}
                      onSelect={commitSelection}
                    >
                      <span className="model-picker-item-label">{m.name}</span>
                      <span className="model-picker-item-meta">
                        {m.default ? '默认' : m.model && m.model !== m.name ? m.model : ''}
                      </span>
                      {effectiveSelectedModel === m.name && <Check size={13} className="model-picker-check" aria-hidden="true" />}
                    </CommandItem>
                  ))}
                </CommandGroup>
              ))}
            </CommandList>
          </Command>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
