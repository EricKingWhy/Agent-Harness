/** lib/highlight — 完成态代码块语法高亮（#99，D18，规格 03 §8）。
 *
 * shiki fine-grained 装配（shiki/core + langs/themes 子路径按需动态导入）：
 * 刻意不走 `import('shiki')` 全量入口——它把 oniguruma wasm（~600KB）拖进模块
 * 图；core + JS RegExp 引擎（forgiving）让 wasm 彻底出局，个别依赖 onig 特性
 * 的语法抛错 → 外层 catch → 纯文本降级。语言为显式白名单（模型高频语言 +
 * 常用别名），白名单外降级纯文本——与票面「无标注/未知不猜」一致，同时把
 * 依赖面控制在有界集合。
 *
 * 单主题 github-dark（D18 高亮 + 容器语义的交点）：.md-code-block 是跨主题
 * 恒定深底的终端块（terminal-bg，见 app.css .model-output .md-code-block），
 * 浅色主题 token 在其上不可读——票面「dark/light 各一套」不适配该容器语义，
 * 恒深底配恒深主题（同 bash-output 的 terminal-fg 策略），双主题零翻转成本。
 *
 * 安全边界（markdown.tsx「不用 dangerouslySetInnerHTML」冻结决策的延续）：
 * 只消费 shiki 的 token 流、渲染 JSX spans——shiki 对 code 文本转义，token
 * 内容再经 React 转义，零 innerHTML 注入面。失败一律返回 null（负缓存），
 * MdCodeBlock 保持纯文本（不白屏）。
 */

import type { HighlighterCore, LanguageInput } from 'shiki/core';

const THEME = 'github-dark';

export interface HighlightedToken {
  content: string;
  color: string;
}

export interface HighlightedCode {
  /** token 行结构：pre 内逐行渲染，换行由渲染层补（保留空白语义）；
   *  空行为空数组（shiki 契约）。 */
  lines: HighlightedToken[][];
}

/** 语言白名单：模型高频语言 + 常用别名。每项是动态导入 thunk——Vite 逐语言
 *  独立 chunk，命中才下载。扩白名单 = 加一行（依赖面有界、按需加载）。 */
const LANGS: Record<string, LanguageInput> = {
  javascript: () => import('shiki/langs/javascript.mjs'),
  js: () => import('shiki/langs/javascript.mjs'),
  typescript: () => import('shiki/langs/typescript.mjs'),
  ts: () => import('shiki/langs/typescript.mjs'),
  tsx: () => import('shiki/langs/tsx.mjs'),
  jsx: () => import('shiki/langs/jsx.mjs'),
  python: () => import('shiki/langs/python.mjs'),
  py: () => import('shiki/langs/python.mjs'),
  bash: () => import('shiki/langs/bash.mjs'),
  sh: () => import('shiki/langs/bash.mjs'),
  shell: () => import('shiki/langs/bash.mjs'),
  json: () => import('shiki/langs/json.mjs'),
  html: () => import('shiki/langs/html.mjs'),
  css: () => import('shiki/langs/css.mjs'),
  go: () => import('shiki/langs/go.mjs'),
  golang: () => import('shiki/langs/go.mjs'),
  rust: () => import('shiki/langs/rust.mjs'),
  rs: () => import('shiki/langs/rust.mjs'),
  java: () => import('shiki/langs/java.mjs'),
  c: () => import('shiki/langs/c.mjs'),
  cpp: () => import('shiki/langs/cpp.mjs'),
  csharp: () => import('shiki/langs/csharp.mjs'),
  cs: () => import('shiki/langs/csharp.mjs'),
  sql: () => import('shiki/langs/sql.mjs'),
  yaml: () => import('shiki/langs/yaml.mjs'),
  yml: () => import('shiki/langs/yaml.mjs'),
  markdown: () => import('shiki/langs/markdown.mjs'),
  md: () => import('shiki/langs/markdown.mjs'),
  diff: () => import('shiki/langs/diff.mjs'),
  xml: () => import('shiki/langs/xml.mjs'),
  toml: () => import('shiki/langs/toml.mjs'),
  dockerfile: () => import('shiki/langs/dockerfile.mjs'),
  docker: () => import('shiki/langs/dockerfile.mjs'),
  ruby: () => import('shiki/langs/ruby.mjs'),
  rb: () => import('shiki/langs/ruby.mjs'),
  php: () => import('shiki/langs/php.mjs'),
  kotlin: () => import('shiki/langs/kotlin.mjs'),
  swift: () => import('shiki/langs/swift.mjs'),
  lua: () => import('shiki/langs/lua.mjs'),
};

let highlighterPromise: Promise<HighlighterCore | null> | null = null;

/** 单例 highlighter（失败缓存 null——后续调用快速降级）。 */
async function getHighlighter(): Promise<HighlighterCore | null> {
  highlighterPromise ??= Promise.all([
    import('shiki/core'),
    import('shiki/themes/github-light.mjs'),
    import('shiki/themes/github-dark.mjs'),
    import('shiki/engine/javascript'),
  ])
    .then(([core, lightTheme, darkTheme, jsEngine]) =>
      core.createHighlighterCore({
        themes: [lightTheme.default, darkTheme.default],
        langs: [],
        engine: jsEngine.createJavaScriptRegexEngine({ forgiving: true }),
      }),
    )
    .catch(() => null);
  return highlighterPromise;
}

/** 模块级缓存（code+lang → 结果 | null）：重渲染零重复 tokenize；
 *  容量上限防长会话膨胀（超限按插入序 FIFO 逐出——有界即可，不追求真 LRU）。 */
const CACHE_LIMIT = 200;
const cache = new Map<string, HighlightedCode | null>();

export async function highlightCode(code: string, lang: string | null): Promise<HighlightedCode | null> {
  const key = `${lang ?? ''}\u0000${code}`;
  const hit = cache.get(key);
  if (hit !== undefined) return hit;
  const result = await highlightInternal(code, lang);
  if (cache.size >= CACHE_LIMIT) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) cache.delete(oldest);
  }
  cache.set(key, result);
  return result;
}

async function highlightInternal(code: string, lang: string | null): Promise<HighlightedCode | null> {
  if (!lang || !code.trim()) return null;
  const langModule = LANGS[lang.toLowerCase()];
  if (!langModule) return null;
  try {
    const hl = await getHighlighter();
    if (!hl) return null;
    await hl.loadLanguage(langModule);
    const tokens = hl.codeToTokens(code, { lang: lang.toLowerCase(), theme: THEME });
    return {
      lines: tokens.tokens.map((lineTokens) =>
        lineTokens.map((t) => ({ content: t.content, color: t.color || '' })),
      ),
    };
  } catch {
    return null;
  }
}
