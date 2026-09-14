/** toolShapes 纯函数契约——后端 df4f7d8 工具结果标记的解析真值。
 * 标记格式以后端 HANDOFF_FRONTEND_SYNC.md §1.3 为准，零伪造：不匹配即 null。 */

import { describe, expect, it } from 'vitest';
import {
  GREP_TRUNCATED_SUFFIX,
  hasGrepTruncatedSuffix,
  parseErrorShape,
  parseReadShape,
  stripGrepTruncatedSuffix,
} from './toolShapes';

describe('parseReadShape — read 续读标记', () => {
  it('完整续读标记解析并从正文剥离', () => {
    const s = parseReadShape({
      content: 'line1\nline2\nline3\n[Showing lines 1-3 of 5000. Use offset=4 to continue.]',
      total_lines: 5000,
    });
    expect(s).not.toBeNull();
    expect(s!.content).toBe('line1\nline2\nline3');
    expect(s!.continuation).toEqual({ shownFrom: 1, shownTo: 3, totalLines: 5000, nextOffset: 4 });
    expect(s!.totalLines).toBe(5000);
    expect(s!.lineTruncated).toBeNull();
  });

  it('中间页标记：offset 与 shownTo+1 一致契约', () => {
    const s = parseReadShape({
      content: 'a\n[Showing lines 2001-4000 of 5000. Use offset=4001 to continue.]',
      total_lines: 5000,
    });
    expect(s!.continuation).toEqual({ shownFrom: 2001, shownTo: 4000, totalLines: 5000, nextOffset: 4001 });
  });

  it('无标记的普通内容原样透传', () => {
    const s = parseReadShape({ content: 'just a file\nwith lines', total_lines: 2 });
    expect(s!.content).toBe('just a file\nwith lines');
    expect(s!.continuation).toBeNull();
    expect(s!.totalLines).toBe(2);
  });

  it('total_lines 缺失 → null（不伪造）', () => {
    const s = parseReadShape({ content: 'x' });
    expect(s!.totalLines).toBeNull();
  });

  it('空文件 content:"" + total_lines:0 → 正常成功形状', () => {
    const s = parseReadShape({ content: '', total_lines: 0 });
    expect(s).not.toBeNull();
    expect(s!.content).toBe('');
    expect(s!.totalLines).toBe(0);
    expect(s!.continuation).toBeNull();
  });

  it('非对象 / 缺 content → null（回退 GenericBlock）', () => {
    expect(parseReadShape(null)).toBeNull();
    expect(parseReadShape('string result')).toBeNull();
    expect(parseReadShape({ total_lines: 3 })).toBeNull();
  });
});

describe('parseReadShape — 单行超长截断标记（不可续读）', () => {
  // OBS-016：正文措辞改过（后端去掉 POSIX 专有命令 `sed` / `head -c` / `tail -c`），
  // 但前缀 `[Line {n} truncated at {bytes} bytes` 与结尾 `]` 是解析契约，形状不变。
  // 旧文案仍躺在历史会话的落盘事件里，两种都必须能解——别删旧用例。
  it('新文案（OBS-016）：解析并从正文剥离', () => {
    const s = parseReadShape({
      content:
        'data\n[Line 2 truncated at 51200 bytes. This single line alone exceeds the read limit, ' +
        'so it cannot be returned in full. Use the bash tool to read a further byte range, ' +
        'or the grep tool to locate the part you need.]',
      total_lines: 2,
    });
    expect(s!.lineTruncated).toEqual({ line: 2, bytes: 51200 });
    expect(s!.content).toBe('data');
    expect(s!.continuation).toBeNull();
  });

  it('旧文案（历史会话已落盘）：同样解析并从正文剥离', () => {
    const s = parseReadShape({
      content: "data\n[Line 2 truncated at 51200 bytes. Use bash with 'sed -n ...']",
      total_lines: 2,
    });
    expect(s!.lineTruncated).toEqual({ line: 2, bytes: 51200 });
    expect(s!.content).toBe('data');
    expect(s!.continuation).toBeNull();
  });

  it('截断字节计数进 bytes（格式化归展示层）', () => {
    const s = parseReadShape({ content: '[Line 1 truncated at 51200 bytes. Use bash with \'sed -n "51,100p"\']' });
    expect(s!.lineTruncated!.bytes).toBe(51200);
  });
});

describe('grep 截断尾巴', () => {
  it('行尾 ... [truncated] 检测', () => {
    expect(hasGrepTruncatedSuffix(`some matching line${GREP_TRUNCATED_SUFFIX}`)).toBe(true);
    expect(hasGrepTruncatedSuffix('normal line')).toBe(false);
    expect(hasGrepTruncatedSuffix('... [truncated] not at end')).toBe(false);
  });

  it('stripGrepTruncatedSuffix：带尾巴的行剥离尾巴、普通行原样返回', () => {
    expect(stripGrepTruncatedSuffix(`some matching line${GREP_TRUNCATED_SUFFIX}`)).toBe('some matching line');
    expect(stripGrepTruncatedSuffix('normal line')).toBe('normal line');
    expect(stripGrepTruncatedSuffix('')).toBe('');
  });
});

// ── da394a9 批：diff 归档 marker / MCP 工具名拆解 ──

describe('parseArtifactMarker', () => {
  it('从截断摘要提取 artifact id 与读回工具名', () => {
    expect(parseArtifactMarker('内容过大已归档。use inspect_artifact(abc-123) 查看全文')).toEqual({
      artifactId: 'abc-123',
      toolName: 'inspect_artifact',
    });
  });

  /* #186 AC4：后端按"与本 store 配对的读回工具"决定 marker 里写哪个名字——
     S3 → inspect_artifact，MinIO / Local → read_artifact，而 Local 是**默认** Provider。
     此前这里只认 inspect_artifact，于是默认部署的 marker 一个都解析不出来：
     archived 永远为 false，归档占位与"统计不可得"全成了死路径。 */
  it('两个工具名都认（read_artifact 是默认部署发的那个）', () => {
    expect(parseArtifactMarker('use read_artifact(0123456789abcdef) to view]')).toEqual({
      artifactId: '0123456789abcdef',
      toolName: 'read_artifact',
    });
  });

  it('工具名原样保留，不被前端替换成另一个', () => {
    expect(parseArtifactMarker('use inspect_artifact(deadbeefdeadbeef)')?.toolName).toBe(
      'inspect_artifact',
    );
  });

  it('无 marker → null', () => {
    expect(parseArtifactMarker('普通 diff 内容')).toBeNull();
    expect(parseArtifactMarker('')).toBeNull();
  });

  it('marker 空 id → null（零伪造）', () => {
    expect(parseArtifactMarker('use inspect_artifact()')).toBeNull();
    expect(parseArtifactMarker('use read_artifact()')).toBeNull();
  });

  it('认不出的工具名 → null（不把别的调用当归档引用）', () => {
    expect(parseArtifactMarker('use some_other_tool(abc-123)')).toBeNull();
  });
});

describe('splitMcpToolName', () => {
  it('mcp__{server}__{tool} 两段拆解', () => {
    expect(splitMcpToolName('mcp__github__list_issues')).toEqual({ server: 'github', tool: 'list_issues' });
  });
  it('tool 含下划线不受影响（首个 __ 后界）', () => {
    expect(splitMcpToolName('mcp__fs__read_file')).toEqual({ server: 'fs', tool: 'read_file' });
  });
  it('非 MCP 名 → null', () => {
    expect(splitMcpToolName('bash')).toBeNull();
    expect(splitMcpToolName('mcp__')).toBeNull();
    expect(splitMcpToolName('mcp__serveronly')).toBeNull();
  });
});
import { parseArtifactMarker, splitMcpToolName } from './toolShapes';

// ── parseErrorShape（PRD §5.2 失败摘要行）──

describe('parseErrorShape — 失败工具 L0 摘要', () => {
  it('ok=false + error_code → 摘要', () => {
    expect(parseErrorShape({ ok: false, error_code: 'TIMEOUT', message: '命令超时' })).toEqual({
      errorCode: 'TIMEOUT',
      message: '命令超时',
    });
  });
  it('成功结果 → null（业务失败≠Tool失败，exit_code 在 data 里）', () => {
    expect(parseErrorShape({ ok: true, data: { exit_code: 1 } })).toBeNull();
  });
  it('无 error_code / 非对象 / 空字符串 → null（零伪造）', () => {
    expect(parseErrorShape({ ok: false, message: 'boom' })).toBeNull();
    expect(parseErrorShape({ ok: false, error_code: '' })).toBeNull();
    expect(parseErrorShape('plain string')).toBeNull();
    expect(parseErrorShape(null)).toBeNull();
  });
  it('message 缺失 → 空串（error_code 单独可渲染）', () => {
    expect(parseErrorShape({ ok: false, error_code: 'SANDBOX_DOWN' })).toEqual({
      errorCode: 'SANDBOX_DOWN',
      message: '',
    });
  });
});
