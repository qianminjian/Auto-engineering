"""中央提示词管理 (Prompt Registry) — v5.6 §B12.

roles/     各 Agent system prompt 正文 (9 个 .md, frontmatter 声明 fragments)
fragments/ B11 可复用行为塑形片段 (跨 Agent 共享)
schema/    output_schema 注入模板 (B 类)

registry.py (T16e) 在此加载 roles/*.md + 组合 fragments + 锁 content hash.
"""
