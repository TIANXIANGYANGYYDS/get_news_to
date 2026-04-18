from typing import Any, Dict, Optional, Protocol, Tuple

import requests


class ProxyProvider(Protocol):
    """
    网络出口提供器接口。

    返回值格式需兼容 requests:
    {
        "http": "http://host:port",
        "https": "http://host:port",
    }

    不可用时返回 None。
    """

    def get_requests_proxies(self) -> Optional[Dict[str, str]]:
        ...

    def on_success(self) -> None:
        ...

    def on_failure(self, exc: Exception) -> None:
        ...


class NoProxyProvider:
    """
    默认实现：不使用代理。
    """

    def get_requests_proxies(self) -> Optional[Dict[str, str]]:
        return None

    def on_success(self) -> None:
        pass

    def on_failure(self, exc: Exception) -> None:
        pass


class ShanchenProxyProvider:
    """
    山城代理 API 接入版（缓存当前代理版）

    逻辑：
    - 默认不会每次请求都切换代理
    - 只在“当前代理不存在”时拉取新代理
    - 当前代理请求失败后，清空并在下一次请求时更换
    """

    def __init__(
        self,
        api_url: str,
        timeout: int = 10,
        scheme: str = "http",
    ) -> None:
        self.api_url = api_url
        self.timeout = timeout
        self.scheme = scheme  # "http" or "socks5"

        self.last_endpoint: Optional[Tuple[str, int]] = None
        self.current_endpoint: Optional[Tuple[str, int]] = None
        self.current_proxies: Optional[Dict[str, str]] = None

    def _extract_ip_port(self, data: Any) -> Optional[Tuple[str, int]]:
        """
        按山城代理文档解析 ip:port。
        优先兼容 JSON 的 list + sever + port。
        同时兼容 text 格式的单行 ip:port。
        """
        if isinstance(data, dict):
            status = str(data.get("status", "")).strip()
            if status and status != "0":
                info = data.get("info", "未知错误")
                print(f"[代理池] 代理接口返回失败 status={status}, info={info}")
                return None

            candidates = data.get("list")
            if isinstance(candidates, list) and candidates:
                item = candidates[0]
                if isinstance(item, dict):
                    ip = (
                        item.get("sever")
                        or item.get("server")
                        or item.get("ip")
                        or item.get("IP")
                        or item.get("host")
                    )
                    port = item.get("port") or item.get("Port")
                    if ip and port:
                        return str(ip).strip(), int(str(port).strip())

        if isinstance(data, str):
            text = data.strip()
            if not text:
                return None

            first_line = text.splitlines()[0].strip()
            if ":" in first_line:
                host, port = first_line.split(":", 1)
                host = host.strip()
                port = port.strip()
                if host and port:
                    return host, int(port)

        return None

    def _fetch_proxy_endpoint(self) -> Optional[Tuple[str, int]]:
        try:
            resp = requests.get(self.api_url, timeout=self.timeout)
            resp.raise_for_status()

            text = resp.text.strip()

            try:
                data = resp.json()
                endpoint = self._extract_ip_port(data)
                if endpoint is None:
                    print(f"[代理池] JSON 已返回，但未解析出 ip:port，原始 JSON: {data}")
                else:
                    print(f"[代理池] 获取到新代理: {endpoint[0]}:{endpoint[1]}")
                self.last_endpoint = endpoint
                return endpoint
            except Exception:
                endpoint = self._extract_ip_port(text)
                if endpoint is None:
                    print(f"[代理池] 文本已返回，但未解析出 ip:port，原始文本: {text}")
                else:
                    print(f"[代理池] 获取到新代理: {endpoint[0]}:{endpoint[1]}")
                self.last_endpoint = endpoint
                return endpoint

        except Exception as e:
            print(f"[代理池] 获取代理失败: {repr(e)}")
            self.last_endpoint = None
            return None

    def _build_proxies_from_endpoint(self, endpoint: Tuple[str, int]) -> Dict[str, str]:
        host, port = endpoint
        proxy_url = f"{self.scheme}://{host}:{port}"
        return {
            "http": proxy_url,
            "https": proxy_url,
        }

    def _clear_current_proxy(self) -> None:
        self.current_endpoint = None
        self.current_proxies = None

    def get_requests_proxies(self) -> Optional[Dict[str, str]]:
        """
        核心逻辑：
        - 如果当前已有代理，则一直复用
        - 如果当前没有代理，才去拉取新的
        """
        if self.current_proxies is not None and self.current_endpoint is not None:
            print(
                f"[代理池] 继续复用当前代理: "
                f"{self.current_endpoint[0]}:{self.current_endpoint[1]}"
            )
            return self.current_proxies

        endpoint = self._fetch_proxy_endpoint()
        if endpoint is None:
            print("[代理池] 当前没有拿到可用代理，本次请求返回 None")
            self._clear_current_proxy()
            return None

        proxies = self._build_proxies_from_endpoint(endpoint)
        self.current_endpoint = endpoint
        self.current_proxies = proxies

        print(f"[代理池] 切换为新代理: {endpoint[0]}:{endpoint[1]}")
        print(f"[代理池] 本次 requests 使用代理: {proxies}")
        return proxies

    def on_success(self) -> None:
        if self.current_endpoint:
            print(
                f"[代理池] 当前代理请求成功，继续复用: "
                f"{self.current_endpoint[0]}:{self.current_endpoint[1]}"
            )

    def on_failure(self, exc: Exception) -> None:
        if self.current_endpoint:
            print(
                f"[代理池] 当前代理请求失败，准备弃用: "
                f"{self.current_endpoint[0]}:{self.current_endpoint[1]} | {repr(exc)}"
            )
        else:
            print(f"[代理池] 请求失败，但当前未记录代理: {repr(exc)}")

        self._clear_current_proxy()


def quick_test_proxy(provider: ProxyProvider) -> None:
    """
    在正式抓取前，先打一个简单请求验证代理是否工作。
    """
    print("=" * 80)
    print("开始代理连通性测试")
    proxies = provider.get_requests_proxies()
    print(f"测试时使用代理: {proxies}")

    try:
        resp = requests.get(
            "http://www.baidu.com",
            timeout=15,
            proxies=proxies,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        print(f"代理测试状态码: {resp.status_code}")
        print(f"代理测试响应前 120 字符: {resp.text[:120]}")
        provider.on_success()
    except Exception as e:
        provider.on_failure(e)
        print(f"代理测试失败: {repr(e)}")
        raise

    print("=" * 80)
