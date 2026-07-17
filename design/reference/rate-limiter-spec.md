# Rate Limiter 模块规格

## 概述

实现一个令牌桶（Token Bucket）限流器。

## 功能需求

1. 支持 `consume(key, tokens=1)` 方法 — 消费令牌，返回 `(allowed: bool, remaining: int)`
2. 支持 `reset(key)` 方法 — 重置指定 key 的桶
3. 默认速率：10 tokens/second，最大桶容量 20
4. 线程安全

## API

```python
class RateLimiter:
    def __init__(self, rate: float = 10.0, capacity: int = 20)
    def consume(self, key: str, tokens: int = 1) -> tuple[bool, int]
    def reset(self, key: str) -> None
```

## 文件

- `src/rate_limiter.py` — RateLimiter 实现
- `tests/test_rate_limiter.py` — 单元测试
