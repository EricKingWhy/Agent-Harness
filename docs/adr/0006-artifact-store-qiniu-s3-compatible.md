# ADR-0006: Artifact Store — 七牛云 Kodo S3 兼容，不做 Local/MinIO

**Status**: Accepted  
**Date**: 2026-09-04  
**Phase**: 5 (Artifact + MinIO + Context Compaction)

## Context

Phase 5 Gate 要求 "MinIO Provider 可替换 Local Provider"（14 §5），规格 06 §3 要求 "接口 SHOULD 保持对象存储抽象，未来可换 S3"。

原始规格方案：Local 文件系统（开发/小型）+ MinIO（正式大文件）。用户在生产环境使用**七牛云 Kodo**（对象存储），不再使用本地文件存储。

三个候选方案：

- A. 按 spec 原文做 Local + MinIO 两个 Provider，七牛以后再加
- B. 做 Local + 七牛 Kodo（用七牛原生 Python SDK `qiniu`）
- C. 做单一 S3 兼容 Provider（用 `aioboto3`），指向七牛云 Kodo 的 S3 兼容端点

## Decision

**Option C**：单一 `S3ArtifactStore`，用 `aioboto3`（async S3 client）对接七牛云 Kodo 的 S3 兼容端点。不做 `LocalArtifactStore`、不做 `MinioArtifactStore`。

- 生产 Provider：`S3ArtifactStore`——endpoint / bucket / access key / secret 走 Settings 配置
- 测试 Provider：`FakeArtifactStore`——纯内存实现，不碰网络
- 集成测试标 `@pytest.mark.qiniu`，默认 skip（需要真实七牛凭证）
- `aioboto3` 可选安装（跟 Phase 3 `docker` SDK 同策略）

## Rationale

- **用户已经用七牛云**——做 Local Provider 是投机性通用，用户明确说"不用本地了"。Simplicity First。
- **S3 兼容同时满足"现在用七牛"和"未来可换"**——七牛云 Kodo 提供 S3 兼容 API；`aioboto3` 的 S3 client 指向七牛 endpoint 时只需要改 `endpoint_url` 配置。未来换 AWS S3 / Cloudflare R2 / 腾讯 COS 同理（它们都是 S3 兼容）。spec 要求的"未来可换 S3"在这一层直接满足。
- **不做七牛原生 SDK**——`qiniu` Python SDK 不是 async-first，绑定厂商私有 API；S3 兼容是开放标准且 async 生态成熟（`aioboto3`）。
- **不做 MinIO**——MinIO 是自建对象存储方案，用户用的是云端七牛，MinIO 适配器是无用的投机抽象。
- **FakeArtifactStore 足够验证可替换性**——Gate 要的是"MinIO Provider 可替换 Local Provider"的**契约证据**（接口隔离），不是部署验证。Fake ↔ S3 的替换测试比 Local ↔ MinIO 的替换测试更干净（不碰文件系统）。

## Consequences

- `ArtifactStore` ABC 定义三个方法：`save()` / `load()` / `inspect()`（line 层面）。
- Settings 新增 `artifact_store_*` 配置组：endpoint / bucket / access_key / secret_key / region。
- `requirements` 加 `aioboto3` 为可选依赖（`optional-dependencies` 下 `artifact` 组）。
- `inspect_artifact` Tool 构造时注入 `ArtifactStore`（不是 `Sandbox`），它是唯一不经过 Sandbox 的 Coding Tool。
