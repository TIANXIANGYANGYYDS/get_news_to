from fastapi import APIRouter, Depends, Request

from domain.models.pipeline_models import TaskCreateRequest

router = APIRouter(prefix="/api/v2", tags=["news-platform"])


def get_app_state(request: Request):
    return request.app.state.container


@router.get("/health")
async def health(container=Depends(get_app_state)):
    return {
        "status": "ok",
        "scheduler_running": container.scheduler_engine.is_running,
    }


@router.post("/tasks")
async def create_task(payload: dict, container=Depends(get_app_state)):
    request = TaskCreateRequest.from_dict(payload)
    task = await container.task_service.create_task(request=request, source="api")
    return {"task_id": task.task_id, "status": task.status.value}


@router.post("/tasks/notify")
async def create_notify_task(payload: dict, container=Depends(get_app_state)):
    parsed = TaskCreateRequest.from_dict(payload)
    request = TaskCreateRequest(task_name="notify_digest", task_type=parsed.task_type, payload=parsed.payload)
    task = await container.task_service.create_task(request=request, source="api")
    return {"task_id": task.task_id, "status": task.status.value}


@router.get("/tasks/dead-letter")
async def list_dead_letters(container=Depends(get_app_state)):
    rows = await container.scheduler_task_repository.list_dead_letters(limit=100)
    return {"rows": [row.to_dict() for row in rows]}
