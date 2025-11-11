from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import tempfile
import subprocess
import os
import shutil
from typing import Dict

app = FastAPI(title="OpenPLC Orchestrator API Service")
SECRET_API_KEY = os.getenv("API_KEY")

# check that the API key is set
if not SECRET_API_KEY:
    raise ValueError("API_KEY environment variable is not set")


ALLOWED_ORIGINS = [
    "https://autonomy-edge.com",
    "https://www.autonomy-edge.com",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=False,
    max_age=86400,  # Cache preflight requests for 24 hours
)

@app.middleware("http")
async def check_api_key(request, call_next):
    api_key = request.headers.get("Authorization")
    if api_key != f"Bearer {SECRET_API_KEY}":
        return JSONResponse(
            status_code=403,
            content={"detail": "Forbidden"},
        )
    return await call_next(request)

@app.post("/hello-world", response_class=JSONResponse)
async def hello_world(request: Request):
    # Parse and validate JSON body
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")
    
    name = data.get("name")
    if not name or not isinstance(name, str):
        raise HTTPException(status_code=400, detail="Missing or invalid 'name' field in JSON body")
    
    return {"message": f"Hello, {name}!"}