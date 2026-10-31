"""Task-authored permission; independent of reviewer intervention grants."""
from pydantic import Field, StrictInt
from .assessment import Category
from .contracts import Strict


class AutomaticRepairPolicy(Strict):
    enabled: bool = False
    categories: list[Category] = Field(default_factory=list,max_length=9)
    max_attempts: StrictInt = Field(default=2,ge=0,le=2)
    allowed_slots: list[StrictInt] = Field(default_factory=list,max_length=24)
    allow_full_frame: bool = False

