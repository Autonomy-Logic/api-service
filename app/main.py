from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import tempfile
import subprocess
import os
import shutil
import ssl
import asyncio
import json
from typing import Dict, Optional
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from datetime import datetime

app = FastAPI(title="OpenPLC Orchestrator API Service")
SECRET_API_KEY = os.getenv("API_KEY")

if not SECRET_API_KEY:
    raise ValueError("API_KEY environment variable is not set")

CERT_STORAGE_DIR = Path(os.getenv("CERT_STORAGE_DIR", "./certs"))
CERT_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

active_connections: Dict[str, WebSocket] = {}


def extract_cn_from_certificate(cert_pem: str) -> Optional[str]:
    """
    Extract the CN (Common Name) from a PEM certificate.
    Returns the CN value or None if not found.
    """
    try:
        cert_bytes = cert_pem.encode('utf-8')
        cert = x509.load_pem_x509_certificate(cert_bytes, default_backend())
        
        for attribute in cert.subject:
            if attribute.oid == x509.oid.NameOID.COMMON_NAME:
                return attribute.value
        
        return None
    except Exception as e:
        raise ValueError(f"Failed to parse certificate: {str(e)}")


def save_agent_certificate(agent_id: str, cert_pem: str) -> None:
    """
    Save an agent's certificate to disk.
    """
    cert_path = CERT_STORAGE_DIR / f"{agent_id}.crt"
    cert_path.write_text(cert_pem)


def get_agent_certificate_path(agent_id: str) -> Optional[Path]:
    """
    Get the path to an agent's certificate if it exists.
    """
    cert_path = CERT_STORAGE_DIR / f"{agent_id}.crt"
    return cert_path if cert_path.exists() else None


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
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")
    
    name = data.get("name")
    if not name or not isinstance(name, str):
        raise HTTPException(status_code=400, detail="Missing or invalid 'name' field in JSON body")
    
    return {"message": f"Hello, {name}!"}


@app.post("/agent/certificate", response_class=JSONResponse)
async def upload_agent_certificate(request: Request):
    """
    Upload an agent certificate. The agent ID must be provided in the request
    and must match the CN field in the certificate.
    
    Expected JSON body:
    {
        "agent_id": "07048933",
        "certificate": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"
    }
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON")
    
    agent_id = data.get("agent_id")
    certificate = data.get("certificate")
    
    if not agent_id or not isinstance(agent_id, str):
        raise HTTPException(status_code=400, detail="Missing or invalid 'agent_id' field")
    
    if not certificate or not isinstance(certificate, str):
        raise HTTPException(status_code=400, detail="Missing or invalid 'certificate' field")
    
    try:
        cn_from_cert = extract_cn_from_certificate(certificate)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    if not cn_from_cert:
        raise HTTPException(status_code=400, detail="Certificate does not contain a CN field")
    
    if cn_from_cert != agent_id:
        raise HTTPException(
            status_code=400, 
            detail=f"Agent ID mismatch: provided '{agent_id}' but certificate CN is '{cn_from_cert}'"
        )
    
    try:
        save_agent_certificate(agent_id, certificate)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save certificate: {str(e)}")
    
    return {
        "message": "Certificate uploaded successfully",
        "agent_id": agent_id
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for orchestrator agents to connect using mTLS.
    This endpoint accepts connections from agents that have their certificates
    registered via the /agent/certificate endpoint.
    """
    await websocket.accept()
    
    agent_id = None
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            topic = message.get("topic")
            payload = message.get("payload", {})
            
            if topic == "heartbeat":
                agent_id = payload.get("id")
                if agent_id:
                    active_connections[agent_id] = websocket
                    print(f"Heartbeat received from agent {agent_id}")
                    print(f"CPU: {payload.get('cpu_usage')}, Memory: {payload.get('memory_usage')}MB, Disk: {payload.get('disk_usage')}MB")
                
                await websocket.send_text(json.dumps({
                    "topic": "heartbeat_ack",
                    "payload": {
                        "timestamp": datetime.now().isoformat()
                    }
                }))
            else:
                print(f"Received message with topic: {topic}")
                
    except WebSocketDisconnect:
        if agent_id and agent_id in active_connections:
            del active_connections[agent_id]
            print(f"Agent {agent_id} disconnected")
    except Exception as e:
        print(f"WebSocket error: {str(e)}")
        if agent_id and agent_id in active_connections:
            del active_connections[agent_id]
