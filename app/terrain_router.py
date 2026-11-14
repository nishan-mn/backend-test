from fastapi import APIRouter, HTTPException
from app.terrain_models import TerrainRequest, TerrainResponse
from app.terrain_service import DatasetMismatchError, DatasetUnavailableError, TerrainService

router = APIRouter(prefix="/api/terrain", tags=["terrain"])
service = TerrainService()

@router.post("/analyze", response_model=TerrainResponse)
def analyze_terrain(request: TerrainRequest) -> TerrainResponse:
    try:
        return service.analyze(**request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatasetMismatchError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except DatasetUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
