from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProxyConfig:
    http: str | None = None
    https: str | None = None


class ProxyProvider:
    def get_proxy(self) -> ProxyConfig:
        return ProxyConfig()
