import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import test_case_agent
from app.logging_setup import configure_logging

configure_logging()

logger = logging.getLogger(__name__)

app = FastAPI()
logger.info("FastAPI 应用已创建，路由: GET /health, /api/test-case-agent/*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(test_case_agent.router, prefix="/api/test-case-agent")


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}
