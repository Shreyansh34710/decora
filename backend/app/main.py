
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.extract import router as extraction_router
from app.api.memory import router as memory_router
from app.api.github import router as github_router


app = FastAPI(
    title="Decora",
    description="Open-source engineering decision recovery",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
allow_origins=[
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://10.7.21.217:5173",
],    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/")
def root():
    return {
        "name": "Decora",
        "status": "running",
        "purpose": "Engineering decision recovery"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


app.include_router(
    extraction_router,
    prefix="/api",
    tags=["Decision Extraction"]
)

app.include_router(
    memory_router,
    prefix="/api",
    tags=["Decision Memory"],
)

app.include_router(
    github_router,
    prefix="/api",
    tags=["GitHub Import"],
)
