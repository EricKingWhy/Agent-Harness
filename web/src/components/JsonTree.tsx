/** JsonTree — Inspector 级 JSON 结构化查看器（纯表现层）。
 *
 *  折叠树 + 叶子类型着色 + 渲染预算：
 *    - defaultDepth 之内的容器默认展开，之外折叠为「N keys / N items」计数；
 *    - 单容器子项超过 JSON_TREE_MAX_CHILDREN 时只渲染前 N 个 + 余量提示行；
 *    - 长字符串显示截断（160 字符）。
 *  真值通道不变：调用方持有全量文本的 CopyButton——此处只是视图裁剪，
 *  与 truncateForDisplay 同级的显示层处理，不删数据（不变量 #22 无关数据本体）。
 */

import { useState } from 'react';
import { ChevronRight } from 'lucide-react';

/** 单容器最多渲染的子项数（超出折叠为余量提示行）。 */
export const JSON_TREE_MAX_CHILDREN = 50;
/** 叶子字符串显示截断长度。 */
const MAX_STRING = 160;

type Json = unknown;

function isContainer(v: Json): v is Record<string, Json> | Json[] {
  return typeof v === 'object' && v !== null;
}

/** 叶子值的展示文本与着色类名（导出以便测试锁定）。 */
export function leafView(v: Json): { text: string; cls: string } {
  if (v === null) return { text: 'null', cls: 'json-literal' };
  switch (typeof v) {
    case 'string': {
      const cut = v.length > MAX_STRING;
      return { text: JSON.stringify(cut ? `${v.slice(0, MAX_STRING)}…` : v), cls: 'json-string' };
    }
    case 'number':
      return { text: String(v), cls: 'json-number' };
    case 'boolean':
      return { text: String(v), cls: 'json-literal' };
    default:
      // function / undefined / symbol 不会出现在 JSON 数据中——兜底文本化
      return { text: String(v), cls: 'json-literal' };
  }
}

interface NodeProps {
  /** 对象 key / 数组 index；root 为 null。 */
  name: string | null;
  /** key 的着色类（对象 key 主色 / 数组 index 降权）。 */
  keyCls: 'json-key' | 'json-index';
  value: Json;
  depth: number;
  defaultDepth: number;
}

const INDENT = 14;

function KeyLabel({ name, keyCls }: { name: string; keyCls: 'json-key' | 'json-index' }) {
  return (
    <>
      <span className={keyCls}>{name}</span>
      <span className="json-punct">: </span>
    </>
  );
}

function JsonNode({ name, keyCls, value, depth, defaultDepth }: NodeProps) {
  const [open, setOpen] = useState(depth < defaultDepth);
  const pad = { paddingLeft: depth * INDENT };

  if (!isContainer(value)) {
    const leaf = leafView(value);
    return (
      <div className="json-row" style={{ paddingLeft: depth * INDENT + 18 }}>
        {name !== null && <KeyLabel name={name} keyCls={keyCls} />}
        <span className={leaf.cls}>{leaf.text}</span>
      </div>
    );
  }

  const isArr = Array.isArray(value);
  const entries: readonly (readonly [string, Json])[] = isArr
    ? (value as Json[]).map((v, i) => [String(i), v] as const)
    : Object.entries(value as Record<string, Json>);
  const braceOpen = isArr ? '[' : '{';
  const braceClose = isArr ? ']' : '}';

  // 空容器：无开关，内联 { } / [ ]
  if (entries.length === 0) {
    return (
      <div className="json-row" style={{ paddingLeft: depth * INDENT + 18 }}>
        {name !== null && <KeyLabel name={name} keyCls={keyCls} />}
        <span className="json-punct">{`${braceOpen} ${braceClose}`}</span>
      </div>
    );
  }

  const shown = entries.slice(0, JSON_TREE_MAX_CHILDREN);
  const hiddenCount = entries.length - shown.length;

  return (
    <div className="json-node">
      <button
        type="button"
        className="json-row json-toggle"
        style={pad}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <ChevronRight size={14} className={`json-chevron${open ? ' json-chevron-open' : ''}`} />
        {name !== null && <KeyLabel name={name} keyCls={keyCls} />}
        <span className="json-punct">{braceOpen}</span>
        {!open && (
          <>
            <span className="json-count">
              {entries.length} {isArr ? 'items' : entries.length === 1 ? 'key' : 'keys'}
            </span>
            <span className="json-punct">{braceClose}</span>
          </>
        )}
      </button>
      {open && (
        <>
          {shown.map(([k, v]) => (
            <JsonNode
              key={k}
              name={k}
              keyCls={isArr ? 'json-index' : 'json-key'}
              value={v}
              depth={depth + 1}
              defaultDepth={defaultDepth}
            />
          ))}
          {hiddenCount > 0 && (
            <div className="json-row json-more" style={{ paddingLeft: (depth + 1) * INDENT + 18 }}>
              … 其余 {hiddenCount} 项已折叠（复制 JSON 取全量）
            </div>
          )}
          <div className="json-row json-close" style={{ paddingLeft: depth * INDENT + 18 }}>
            <span className="json-punct">{braceClose}</span>
          </div>
        </>
      )}
    </div>
  );
}

export function JsonTree({
  value,
  defaultDepth = 2,
  className,
}: {
  value: Json;
  defaultDepth?: number;
  className?: string;
}) {
  return (
    <div className={`json-tree${className ? ` ${className}` : ''}`}>
      <JsonNode name={null} keyCls="json-key" value={value} depth={0} defaultDepth={defaultDepth} />
    </div>
  );
}
