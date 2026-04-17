from dataclasses import dataclass, field


@dataclass
class HealthResponse:
    status: str
    scheduler_running: bool


@dataclass
class TriggerTaskRequest:
    task_name: str
    task_type: str = "manual"
    payload: dict = field(default_factory=dict)


@dataclass
class TriggerTaskResponse:
    task_id: str
    status: str
