/** UI-01（R6）：快捷键文案的平台检测——纯函数，ua 注入以便单测。
 *  禁止再硬编码 ⌘（评审 Minor：Windows 上显示 ⌘+Enter）。 */
import { describe, expect, it } from 'vitest';
import { isApplePlatform, modKey } from './platform';

const MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36';
const WIN = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36';
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15';

describe('isApplePlatform — 苹果系平台判定（含 iOS）', () => {
  it('macOS UA → true', () => {
    expect(isApplePlatform(MAC)).toBe(true);
  });
  it('iPhone UA → true（iPad/iPod 同族）', () => {
    expect(isApplePlatform(IPHONE)).toBe(true);
  });
  it('Windows UA → false', () => {
    expect(isApplePlatform(WIN)).toBe(false);
  });
  it('iPadOS 13+ 桌面模式 UA（报 Macintosh）→ true：有硬件键盘时 ⌘ 存在，方向正确', () => {
    expect(isApplePlatform(MAC)).toBe(true);
  });
});

describe('modKey — 修饰键文案：macOS ⌘ / 其余 Ctrl', () => {
  it('macOS → ⌘', () => {
    expect(modKey(MAC)).toBe('⌘');
  });
  it('Windows → Ctrl', () => {
    expect(modKey(WIN)).toBe('Ctrl');
  });
  it('缺省参数走运行时 navigator（冒烟：非空字符串）', () => {
    expect(modKey().length).toBeGreaterThan(0);
  });
});
