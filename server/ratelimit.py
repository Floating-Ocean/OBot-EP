"""进程内滑动窗口限速。

用途很具体：登录和注册接口都会做一次 PBKDF2（26 万轮），而且注册还能凭空写库。
这两个接口不设防的话，一个脚本就能把 CPU 占满、把用户表刷爆。

刻意不引入 Redis / slowapi：这是个单进程小工具，一个带锁的字典就够了。
代价是限速状态不跨进程、重启即清空 —— 对这个场景可以接受。

键一律用「服务端自己知道的东西」：客户端地址取自连接（request.client），
不看 X-Forwarded-For，否则攻击者换个头就能绕过限速。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

MAX_KEYS = 20_000


class RateLimiter:
    """固定窗口 + 滑动队列：每个键保留窗口内的命中时间。"""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = max(0, int(limit))
        self.window = float(window_seconds)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.limit > 0 and self.window > 0

    def _prune(self, hits: deque[float], now: float) -> None:
        cutoff = now - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()

    def retry_after(self, key: str) -> int:
        """被限速时返回建议等待的秒数；未被限速返回 0。"""
        if not self.enabled:
            return 0
        now = time.monotonic()
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0
            self._prune(hits, now)
            if len(hits) < self.limit:
                return 0
            return max(1, int(self.window - (now - hits[0])) + 1)

    def record(self, key: str) -> None:
        """记一次命中。"""
        if not self.enabled:
            return
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > MAX_KEYS:
                # 只在字典过大时整体清理一次，避免每个请求都做 O(n) 扫描
                stale = [item for item, hits in self._hits.items() if not hits or hits[-1] <= now - self.window]
                for item in stale:
                    self._hits.pop(item, None)
                if len(self._hits) > MAX_KEYS:
                    self._hits.clear()
            hits = self._hits[key]
            self._prune(hits, now)
            hits.append(now)

    def clear(self, key: str) -> None:
        """清掉某个键的计数（登录成功后用，避免正常人被自己的失败次数拖累）。"""
        if not self.enabled:
            return
        with self._lock:
            self._hits.pop(key, None)
