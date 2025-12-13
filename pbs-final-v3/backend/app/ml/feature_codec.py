from __future__ import annotations
import json

def to_dict(obj) -> dict:
    # pydantic v2
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    # pydantic v1
    if hasattr(obj, "dict"):
        return obj.dict()
    # dataclass / plain object
    try:
        return dict(vars(obj))
    except Exception:
        return json.loads(json.dumps(obj))
