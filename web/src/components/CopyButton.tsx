/** CopyButton — 复制小按钮（调研借鉴：AI chat 界面标配动作，Setproduct
 *  《Designing AI chat interfaces》pitfall #9「代码块无复制按钮」）。
 *
 * Copy → Check 短反馈（1.6s）；ghost 变体默认透明，父容器 hover 浮现——
 * 动作常驻会与正文抢视觉（Chanel 原则：出门前摘掉一件配饰）。
 * 无障碍：DOM 位置排在正文之后，成功态同时写入 aria-label 与 title。
 */

import { memo, useEffect, useRef, useState } from 'react';
import { Check, Copy } from 'lucide-react';

interface Props {
  /** 被复制的完整文本（展示层截断不影响这里——复制的是全量）。 */
  text: string;
  label?: string;
}

export const CopyButton = memo(function CopyButton({ text, label = '复制' }: Props) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(() => () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
  }, []);

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // 非安全上下文回退（clipboard API 仅 https/localhost 可用）：
      // 临时 textarea + execCommand，同步路径，剪贴板历史上广泛支持。
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }
    setCopied(true);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <button
      type="button"
      className={`copy-btn${copied ? ' copied' : ''}`}
      onClick={() => { void onCopy(); }}
      aria-label={copied ? '已复制' : label}
      title={copied ? '已复制' : label}
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
});
