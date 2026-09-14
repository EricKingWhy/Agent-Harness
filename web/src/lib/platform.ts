/** 平台检测（UI-01，PRD R6）：快捷键文案按平台显示，禁止硬编码 ⌘。
 *
 *  纯函数、ua 注入——单测直接喂字符串；组件里用缺省参数走运行时 navigator。 */

export function isApplePlatform(ua: string = navigator.userAgent): boolean {
  return /Mac|iP(hone|ad|od)/.test(ua);
}

/** 修饰键文案：macOS/iOS ⌘，其余 Ctrl。 */
export function modKey(ua?: string): string {
  return isApplePlatform(ua) ? '⌘' : 'Ctrl';
}
