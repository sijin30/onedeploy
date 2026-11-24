import uuid
from datetime import datetime

from pydantic import BaseModel


class IncidentResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    service_id: uuid.UUID
    container_id: str
    status: str
    detection: str
    action: str | None
    outcome: str | None
    failed_checks: int
    restart_attempts: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
