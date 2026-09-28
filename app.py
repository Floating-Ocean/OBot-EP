"""兼容旧入口：`python app.py` 直接起服务。

用法：
    python app.py                       # 本机 http://127.0.0.1:8000
    python app.py --host 0.0.0.0        # 监听所有网卡（局域网可访问）

监听 0.0.0.0 之前请先读 README 的「对外提供服务」一节：默认是明文 HTTP，
会话 Cookie 与口令会在网络上裸奔，建议只在受信任的内网里这样做，
或者在前面挂一层 HTTPS 反向代理。
"""

from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="OBot-EP backend")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="监听地址；0.0.0.0 = 所有网卡（默认 127.0.0.1，仅本机）",
    )
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    args = parser.parse_args()

    # 让应用自己知道绑在哪个地址上，启动时才能给出「正在对网络提供服务」的告警
    os.environ["OBOT_EP_BIND_HOST"] = args.host

    uvicorn.run(
        "server.app:app", host=args.host, port=args.port, reload=args.reload
    )


if __name__ == "__main__":
    main()
