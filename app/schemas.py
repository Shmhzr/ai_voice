# app/schemas.py
from pydantic import BaseModel
from typing import Any, Dict, Optional

class GenericItem(BaseModel):
    data: Dict[str, Any]

class PushResponse(BaseModel):
    key: str

class SetResponse(BaseModel):
    success: bool

class GetResponse(BaseModel):
    data: Optional[Any]
