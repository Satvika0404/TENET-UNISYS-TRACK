from fastapi import APIRouter
from ..services.storage import list_resources_latest
from ..models.schemas import ResourceSnapshot

router = APIRouter(prefix="/resources")

@router.get("", response_model=list[ResourceSnapshot])
def list_resources():
    return list_resources_latest(limit=500)
