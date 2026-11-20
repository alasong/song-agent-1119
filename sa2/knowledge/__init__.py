"""知识面：世界知识是数据，机制是代码。

对外只有四个名字：`load`（读 JSON）、`text`（读提示文本）、`reload`（清缓存）、
`KnowledgeError`（加载失败一律用它大声报）。
"""
from .loader import DATA, KnowledgeError, SCHEMA, load, reload, text

__all__ = ["DATA", "KnowledgeError", "SCHEMA", "load", "reload", "text"]