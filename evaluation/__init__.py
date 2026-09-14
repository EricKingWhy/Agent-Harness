"""项目自有评测（spec 12 §5，ADR-0018 D9）。

Eval Runner 调真实 AgentRuntime（绝不为评测重写 Runtime）；Langfuse
Datasets/Experiments 承载云端侧，本地 datasets/*.jsonl 是真相源。
"""
