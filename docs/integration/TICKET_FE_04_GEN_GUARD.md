# Ticket FE-04：useSession 竞态守卫在 catch 分支缺失

> **Spec**：Issue #140
> **车道**：前端 `D:\intelligence-agent-frontend`（`feat/frontend`）
> **优先级**：FE（前端竞态）
> **验收走法**：先写红灯 e2e，再修码，再见绿灯。

---

## 背景

`web/src/hooks/useSession.ts` 用 `streamGenRef` + 局部 `gen` 计数守卫并发竞态——每次发起（`submitTask`/`sendFollowUp`）自增 `gen`，SSE 消费机器与重连/停摆检查在回调里 `if (streamGenRef.current !== gen) return;` 丢弃过期回调。

审计发现：**`submitTask` 与 `sendFollowUp` 两个块的 `catch` 分支缺少同一守卫**，直接改写最新句柄的 UI 态：

```ts
// submitTask catch（line 633）
} catch (e) {
  streamGenRef.current += 1;          // 又自增一次
  setMode({ kind: 'idle' });
  setError(`提交失败：${(e as Error).message}`);   // 无条件写 error
}

// sendFollowUp catch（line 674）
} catch (e) {
  streamGenRef.current += 1;
  setMode({ kind: 'idle' });
  setError(`续聊失败：${(e as Error).message}`);   // 无条件写 error
}
```

**缺陷模式**：当用户在旧请求（超时/网络失败/422）之后立即发起新请求，旧请求的 `catch` 可能在 `gen` 已被新请求自增后才触发。此时 `streamGenRef.current !== gen`（旧 gen）本应被拒，但因为没有守卫，旧失败会 `setMode({kind:'idle'})` + `setError(...)`，**把新会话正在跑的 UI 态污染成 idle + 报错**。

## 现状（`feat/frontend` @ `89631f1`）

- `submitTask` catch：`useSession.ts:633-637`（缺 guard）
- `sendFollowUp` catch：`useSession.ts:674-677`（缺 guard）
- 对比：成功分支与 SSE 消费机器（line 405/471/483/509/538/543/574）均已有 `streamGenRef.current !== gen` 守卫。

## 要做什么

在两个 `catch` 块顶部补上与成功分支一致的守卫，让过期请求不得改写最新句柄：

```ts
} catch (e) {
  if (streamGenRef.current !== gen) return;   // 旧请求迟到失败：丢弃，不污染新会话
  streamGenRef.current += 1;
  setMode({ kind: 'idle' });
  setError(...);
}
```

- 守卫放 `catch` 第一行（在 `streamGenRef.current += 1` **之前**）——保证过期请求连自增都不做。
- 不重构取消/超时机制；只补守卫。

## 回归测试（Playwright e2e）

**接缝**：`web/e2e/fixtures.ts` 的 `routeApi`（扩一个「延迟失败」的续聊 mock 分支），配合现有 `continuation.spec.ts` 模式。

**场景**（交错竞态，红灯版）：
1. 发起任务 A，其续聊 POST 被 mock 成一个**缓慢、最终失败**的响应；
2. 在任务 A 尚在途时立即发起任务 B（gen 自增到新值）；
3. 任务 A 的失败响应迟到返回（此时 gen 已是 B 的）——应被守卫丢弃；
4. 断言**最终 UI 态由任务 B 决定**（不出现任务 A 的 `setMode idle` / `setError` 污染任务 B 的 live 态）。

**判定**：修复前该场景 redis 呈现被 A 污染（红灯）；修复后 A 的迟到失败被丢弃、B 保持 live（绿灯）。

> 注：续聊入口（`sendFollowUp`）无现有 e2e 覆盖失败路径，故该场景同时首次覆盖续聊失败路径——非浅层单调用者，直击真实交错模式。

## 不要做什么

- ❌ 不重构 `useSession` 的取消/超时/停摆机制。
- ❌ 不改成功分支或 SSE 消费机器（它们已有正确守卫）。
- ❌ 不引入额外抽象。
