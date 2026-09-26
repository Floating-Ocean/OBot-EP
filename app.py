"""兼容旧入口：`python app.py` 直接起服务。"""

from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run("server.app:app", host="127.0.0.1", port=8000, reload=False)
