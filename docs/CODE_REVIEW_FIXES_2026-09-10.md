# Code-Review 修复交付说明（2026-09-10）

> 起因：用户问「你做 code-review 了吗？」——我此前跑完了全部门禁（tsc/vitest/oxlint/
> playwright/perf/build），但**门禁只证明「能跑」，不证明「对」**。补跑双轴 code-review
> （Standards + Spec）后发现 3 类问题，全部已修。

## 一句话结论

**Code-review 抓出 1 个我自己引入的回归（12 条 e2e 失败）+ 1 个债务（catalog drift）+
4 处集成文档事实错误。全部修复并验证，e2e 从 12 failed / 46 passed → 58/58 全绿。**

## 分支状态

| 项 | 值 |
| --- | --- |
| 分支 | `feat/frontend` |
| 远端 `origin/feat/frontend` | **`4b45bc5`** ✅ **推送成功**（`f2b4929..4b45bc5`） |
| 本地 HEAD | **`eb999bc`**（集成文档同步，**待推送**） |
| 远端 `origin/main` | **`ebb2d68`**（已从 `977b319` 前进——集成 AI 合了后端 session 集成） |
| ahead / behind vs main | **5 / 6** |

### ✅ 上一轮推送已完成

```text
$ git -C D:/intelligence-agent-frontend push origin feat/frontend
   f2b4929..4b45bc5  feat/frontend -> feat/frontend
```
`git ls-remote` 复核：`refs/heads/feat/frontend` = `4b45bc52bca2e87e8dacb16b566e319aa793ddd9` ✅

### ⚠️ 新增 commit `eb999bc` 需要再推一次

`main` 在推送后前进到 `ebb2d68`，集成提示词里的拓扑数字全部过期，已同步订正为
新 commit。请在终端再执行：

```bash
git -C D:/intelligence-agent-frontend push origin feat/frontend
```

推送后自检：

```bash
git ls-remote origin feat/frontend   # 应为 eb999bcf91c9ff9a6bb0748b8e14fc83ae488096
```

## Commit 清单（本批）

| commit | 内容 |
| --- | --- |
| `eb999bc` | docs(integration): 集成提示词同步 main 新 tip `ebb2d68` + 本分支 tip `4b45bc5`（**待推送**） |
| `4b45bc5` | fix(web): code-review 修复——picker 键盘焦点落到 listbox + 长目录 fixture 去重（✅ 已推送） |
| `f2b4929` | docs(integration): 重写集成交接提示词至真实拓扑 + Tracker 勘误（✅ 已推送） |
| `949c92a` | fix(web): F-DEFER-1 短目录隐藏搜索框——补 `.hidden` CSS + e2e；修正被暴露的 4 个坏断言（✅ 已推送） |
| `cddea36` | feat(web): T9 #139 轮次标签 UI——`turn_index` 落到当轮 + `TurnView` 渲染（✅ 已推送） |

---

## 附：`main` 前进到 `ebb2d68` 的复核记录

推送 `4b45bc5` 后复核远端，发现 `main` 已从 `977b319` 前进到 **`ebb2d68`**
（集成 AI 合入了后端 session 集成：`src/agent_harness/**` 6 个文件 + `CONTEXT.md` + 2 docs）。

**「无冲突」结论不变**——`ebb2d68` 改的全是后端与其他 docs，与本分支 `web/**` 零重叠：

```text
$ git merge-tree --write-tree --name-only 4b45bc5 ebb2d68
e0998e928ae3c7d022cea1547b18cdfde56d1b93      # 只有 tree 哈希，无冲突段
```

交叉验证（双侧文件交集为空）：

```bash
comm -12 <(git diff --name-only c00f742 HEAD | sort) \
         <(git diff --name-only c00f742 ebb2d68 | sort)   # → 空
```

集成提示词中的相关数字已全部同步（`ahead 3→4`、`behind 2→6`、
`tree 8f35c93→e0998e9`、main 侧改动描述）——见 commit `eb999bc`。

> **教训**：远端 `main` 会随时前进，集成文档里的哈希只是快照。
> 写「无冲突」结论时**必须同时给出重跑命令**并标注「集成时以实测为准」，
> 否则文档一过期就会误导集成 AI。**每次收尾都应 `git ls-remote` 复核一次。**

---

## 一、回归修复（我上一批引入，12 条 e2e 失败）

### 症状
完整 e2e 从 0 failed 变 **12 failed / 46 passed**，全部卡在
`expect(trigger).toContainText(expected)`（`fixtures.ts` 的 `pickControl`）。

### 探针实测的根因链
我上一批把 `pickControl` 里的 `await combo.fill('')` 改成守卫式
`if (await combo.isVisible()) await combo.fill('')`，以为「短目录下跳过 fill」更安全。
**实测证明两条路都是错的**：

| 情形 | 实测结果 |
| --- | --- |
| 短目录（搜索框隐藏） | 该 `role="combobox"`（`CommandInput` 本身）被 `.hidden` 的 wrap 包住，**rect 为 0×0** → `fill` 等不到可交互状态 → **挂起 30s 超时** |
| 长目录 | `getByRole('combobox', { name: '权限模式' })` **命中 0 个**（aria-label 不落在 input 上）→ 同样挂起 |

**真正的根因**：浮层打开后 `document.activeElement` 是 popover 容器
（`DIV[role="dialog"]`），**不是** trigger，也不是 input。箭头键/Enter 因此没有落到
cmdk 的方向键承接者（`[role="listbox"]`，`tabIndex=-1`）上，选中永不提交。

> 原实现「碰巧能工作」是因为 `fill()` 会把焦点强推进 input；换到 listbox 判开后，
> 这个副作用消失了，隐藏缺陷才暴露。

### 正解
显式把焦点落到 listbox —— **长短目录同一路径，无分支**：

```ts
const listbox = page.locator('[role="listbox"]:visible').last();  // :visible 排除关闭动画残留
await trigger.focus();
await page.keyboard.press('Enter');
await expect(listbox).toBeVisible();
await listbox.focus();          // ← 关键：焦点交给 cmdk 的承接者
for (let i = 0; i < n; i++) await page.keyboard.press('ArrowDown');
await page.keyboard.press('Enter');
```

`:visible` 是必需的：连续两次打开时，关闭动画期间上一层 listbox 仍在 DOM，
裸选择器会命中 2 个 → `strict mode violation`（实测）。

### 连带修正
`context-providers.spec.ts` / `continuation.spec.ts` 的多选 toggle 同样受益于该修正
（打开后直接 Enter 选不中 → 补 `listbox.focus()`）。

---

## 二、Standards 轴发现：catalog drift（去重）

`fixtures.ts:110` 明确写着约定：

> 多个 spec 共用同一份，避免各自复制后静默漂移（code-review：catalog drift）。

**而我正是在 3 个 spec 里各写了一份长目录**——直接违反本仓库自己记录的约定。

### 修复
抽为 `fixtures.ts` 公共导出（`longCatalog()` 支持 `highlight` 参数表达语义差异）：

```ts
export function longCatalog(prefix, n, highlight?: { index: number; label: string })
export const SEARCHABLE_MODELS   // MODELS + 2 = 5，+1 默认链 = 6 > 5
export const LONG_MODELS         // SEARCHABLE_MODELS + 2 = 7，+1 = 8 > 5
```

3 个 spec 改为引用公共导出；`control-row` 的 `Ask Each Time` 语义用
`longCatalog('mode', 6, { index: 2, label: 'Ask Each Time' })` 表达。

---

## 三、Spec 轴发现：集成文档 4 处事实错误（已勘误）

`docs/integration/FRONTEND_INTEGRATION_PROMPT.md` 是交给集成 AI 的**唯一指令**，
写错会直接误导合并。Spec agent 逐条核对后，实测数据如下：

| 项 | 我原写的 | 实测真值 | 命令 |
| --- | --- | --- | --- |
| ahead | 1 | **3**（+本次 = 4） | `git rev-list --count main..HEAD` |
| behind | 0 | **2** | `git rev-list --count HEAD..main` |
| `cddea36` 在 main | 「已在 main」 | **NO** | `git merge-base --is-ancestor cddea36 977b319` |
| merge-tree 哈希 | `382100d` | **`8f35c93`** | `git merge-tree --write-tree f2b4929 977b319` |
| e2e 通过数 | 46 | **58** | `npx playwright test` |

### 需要澄清的一点
「两侧改动**零重叠**」这个**结论本身是对的**，我错在**推理和数字**：

- `main` 侧自 merge-base `c00f742` 起只改了 `docs/PHASE_STATUS.md`（1 个文件）
- `feat/frontend` 侧 15 个文件里**不含** `PHASE_STATUS.md`
- 所以合并不是 fast-forward（behind 2）但**确实无冲突**

`behind 2` 的来源：`main` 上的 `9964adc`（merge commit）+ `977b319`（PHASE_STATUS 回填）。

---

## 四、门禁证据（全部在修复后重跑）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| Type check | `npx tsc --noEmit` | ✅ 0 错误 |
| 单元测试 | `npx vitest run` | ✅ **27 files / 416 passed**（不回退） |
| e2e | `npx playwright test` | ✅ **58 passed**（双 viewport；修复前 12 failed） |
| 性能 | `npx vitest run -c vitest.perf.config.ts` | ✅ **2 files / 12 passed** |
| Lint | `npx oxlint` | ✅ **0 error / 35 warning**（基线，无新增） |

> 跑 e2e / build 前先 `rm -rf web/test-results web/dist`，否则会被沙箱 safe-delete 守卫拦截。

## 五、附带解决的 git 故障（非本次代码改动）

施工开始时发现**本地仓库对象库被沙箱清扫**：`objects/pack/*.pack` 全部消失（只剩 `.idx`）、
`refs/` 目录整个不见 → git 直接报 `not a git repository`。

- **零数据损失**：`git ls-remote` 确认 origin 上 `f2b4929` / `977b319` 完好，工作区文件也全在
- **恢复方式**：绕过损坏的 gitdir，在 `D:\intelligence-agent-frontend` 原地 `git init` +
  `remote add` + `fetch`（对象立刻可读），再手工重建 ref（`refs/heads/feat/` 需子目录，
  被沙箱清扫，须最后一步写入）
- 损坏的 `.git` 已备份至 `.scratch/git-recovery-20260910/.git-broken-backup`
- ⚠️ `D:\intelligence-agent`（主仓库）**未被触碰**——它同样受影响，请自行留意

## 六、剩余事项

1. **推送 `eb999bc`**（你在终端执行，命令见上）——`4b45bc5` 已推送成功 ✅
2. `docs/HANDOFF_WORKBUDDY_FRONTEND.md` 等 4 个未跟踪文档：判定是留是删（本次未动）
3. `test-results/` 建议加入 `.gitignore`
4. **主仓库 `D:\intelligence-agent` 的对象库可能同样损坏**——合并前请先验证
5. **合并前重跑 `merge-tree`**：`main` 已前进过一次，集成时请重新实测，勿沿用 `e0998e9`
