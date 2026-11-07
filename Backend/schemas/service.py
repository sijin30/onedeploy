import uuid
from datetime import datetime

from pydantic import BaseModel


class ServiceCreate(BaseModel):
    name: str


class ServiceResponse(BaseModel):
    id: uuid.UUID
    name: str
    project_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}