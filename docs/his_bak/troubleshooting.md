# ae Troubleshooting

## CHECKPOINT_LOAD_FAILED

原因: checkpoint SQLite 文件损坏或 schema 不匹配。

解决:
```bash
# 列出所有 checkpoint
ae checkpoint list
# 删除损坏的 checkpoint
ae checkpoint v2 delete <checkpoint_id>
```

## CONFIG_MISSING_API_KEY

原因: `ANTHROPIC_API_KEY` 未设置。

解决:
```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
# 或写入 ~/.zshrc 永久生效
```

## BUDGET_EXCEEDED

原因: 单次 dev-loop 消耗超过 `--max-tokens` 限制。

解决:
```bash
# 提高 token 预算
ae dev-loop "complex requirement" --max-tokens 50000
```

## pytest 超时

原因: 单个测试超过 60s。

解决: 检查 teardown 或 fixture leak。在 pytest --timeout=120 增加时间。

## git 仓库不干净

原因: 未提交的变更导致 Gate check 失败。

解决:
```bash
git add <files> && git commit -m "WIP"
```

## SQLiteCheckpointStore 锁定

原因: 另一个进程持有 checkpoint db。

解决:
```bash
# 查找锁文件
ls -la .ae-checkpoints/*.db-journal
# 杀掉持有进程 (如有)
lsof .ae-checkpoints/
```
