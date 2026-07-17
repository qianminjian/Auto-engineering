# Data Pipeline 模块规格

## 概述

实现一个简单的 ETL 数据管道。

## 功能需求

1. `extract(source)` — 从 JSON 文件读取数据
2. `transform(data, rules)` — 应用转换规则（filter/map/reduce）
3. `load(data, target)` — 写入目标 JSON 文件
4. 管道支持链式调用 `Pipeline().extract(s).transform(r).load(t)`

## 文件

- `src/pipeline.py` — Pipeline 实现
- `tests/test_pipeline.py` — 单元测试
