from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseNotifier(ABC):
    @abstractmethod
    async def send(self, title: str, content: str, extra: dict[str, Any] | None = None) -> None:
        raise NotImplementedError
