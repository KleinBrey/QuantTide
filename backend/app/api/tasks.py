"""任务接口：接收表单，将具体操作交给 TaskService。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.schemas import TaskEnabled, TaskInput, TaskOrder
from backend.app.services.task_service import TaskService
from backend.scripts.registry import script_catalog

from .dependencies import get_task_service

router = APIRouter(prefix="/tasks", tags=["任务"])
Service = Annotated[TaskService, Depends(get_task_service)]


@router.get("/scripts")
def list_scripts(service: Service):
    return {
        "scripts": script_catalog(),
        "timezone": service.settings.scheduler_timezone,
        "scheduler_enabled": service.settings.scheduler_enabled,
    }


@router.get("")
def list_tasks(service: Service):
    return service.list_tasks()


@router.post("", status_code=201)
def create_task(body: TaskInput, service: Service):
    return service.create_task(body.model_dump())


@router.put("/order")
def reorder_tasks(body: TaskOrder, service: Service):
    service.reorder_tasks(body.ids)
    return {"status": "success"}


@router.put("/{task_id}")
def update_task(task_id: int, body: TaskInput, service: Service):
    return service.update_task(task_id, body.model_dump())


@router.patch("/{task_id}")
def enable_task(task_id: int, body: TaskEnabled, service: Service):
    return service.set_enabled(task_id, body.enabled)


@router.delete("/{task_id}")
def delete_task(task_id: int, service: Service):
    service.delete_task(task_id)
    return {"status": "success"}


@router.post("/{task_id}/run")
def run_task(task_id: int, service: Service):
    # 普通 def 路由由 FastAPI 在线程池执行，不阻塞 API 的事件循环。
    return service.execute(task_id)
