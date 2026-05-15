from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.logging_setup import configure_logging

from . import test_case_agent

configure_logging()

app = FastAPI()

app.include_router(test_case_agent.router, prefix="/api/test-case-agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}
