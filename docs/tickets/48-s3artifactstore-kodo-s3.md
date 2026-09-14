# #48 — S3ArtifactStore (七牛云 Kodo S3 兼容)

> **Snapshot.** GitHub is the single source of truth.
> Refresh with `python scripts/snapshot_tickets.py`.

- **State**: CLOSED
- **Labels**: ready-for-agent
- **Assignees**: unassigned
- **Author**: EricKingWhy
- **Created**: 2026-09-04T06:01:11Z
- **Closed**: 2026-09-04T06:58:52Z
- **Parent**: #44
- **Blocked by**: #45
- **GitHub**: https://github.com/EricKingWhy/intelligence-agent/issues/48

---

## Parent

Phase 5 Spec #44

## What to build

ArtifactStore 的生产 Provider——用 aioboto3 对接七牛云 Kodo 的 S3 兼容端点。endpoint / bucket / access_key / secret_key / region 走 Settings 配置。实现 save / load / inspect 三个方法，行为与 FakeArtifactStore 完全一致（替换可验证）。

单元测试 mock aioboto3 client 验证 S3 调用参数（put_object / get_object / 正确的 key 格式）。集成测试标 `@pytest.mark.qiniu` 默认 skip，需要真实七牛凭证才能跑。

端到端：S3ArtifactStore.save → load → inspect 全链路在 mock 下通过；替换 FakeArtifactStore 行为一致。

## Acceptance criteria

- [ ] `S3ArtifactStore` 实现 ArtifactStore ABC，用 aioboto3 的 S3 client
- [ ] save：put_object 到 bucket，key 格式 = `{session_id}/{artifact_id}`，返回 Artifact 元数据
- [ ] load：get_object 从 bucket 读回完整内容 + 元数据
- [ ] inspect：get_object 读回内容后按行/关键词切片（复用 FakeArtifactStore 的切片逻辑或共享工具函数）
- [ ] Settings 增加 artifact_store_endpoint / bucket / access_key / secret_key / region
- [ ] aioboto3 加入 optional-dependencies (artifact 组)
- [ ] 单元测试 mock aioboto3 验证调用参数
- [ ] 集成测试 @pytest.mark.qiniu 默认 skip
- [ ] S3ArtifactStore 与 FakeArtifactStore 通过同一套契约测试（替换可验证）

## Blocked by

- #45 (ArtifactStore ABC)
