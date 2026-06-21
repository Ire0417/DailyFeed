"""启动后端 API 服务器（开发模式）."""
import uvicorn
from internal.config.settings import settings

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level="info",
    )
