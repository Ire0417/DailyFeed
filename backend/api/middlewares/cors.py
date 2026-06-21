from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class CORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        if request.method == "OPTIONS":
            return JSONResponse(status_code=204, content={}, headers=dict(response.headers))
        return response
