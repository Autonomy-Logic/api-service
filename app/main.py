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
from urllib.parse import unquote
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from datetime import datetime
import socketio

app = FastAPI(title="OpenPLC Orchestrator API Service")
SECRET_API_KEY = os.getenv("API_KEY")

if not SECRET_API_KEY:
    raise ValueError("API_KEY environment variable is not set")

CERT_STORAGE_DIR = Path(os.getenv("CERT_STORAGE_DIR", "./certs"))
CERT_STORAGE_DIR.mkdir(parents=True, exist_ok=True)

sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    logger=True,
    engineio_logger=True
)

active_connections: Dict[str, str] = {}  # agent_id -> session_id mapping


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
    if request.url.path.startswith("/ws") or request.url.path.startswith("/socket.io"):
        return await call_next(request)
    
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


def validate_client_certificate(cert_pem: str) -> Optional[str]:
    """
    Validate a client certificate against stored certificates.
    Returns the agent_id if valid, None otherwise.
    """
    try:
        cn = extract_cn_from_certificate(cert_pem)
        if not cn:
            return None
        
        stored_cert_path = get_agent_certificate_path(cn)
        if not stored_cert_path:
            return None
        
        stored_cert = stored_cert_path.read_text()
        
        if cert_pem.strip() == stored_cert.strip():
            return cn
        
        return None
    except Exception as e:
        print(f"Certificate validation error: {str(e)}")
        return None


@sio.event
async def connect(sid, environ):
    """
    Handle Socket.IO client connection with mTLS certificate validation.
    """
    print(f"Socket.IO connection attempt from session {sid}")
    
    client_cert_header = environ.get('HTTP_X_SSL_CLIENT_CERT', '')
    
    if client_cert_header:
        print(f"Received client certificate header (length: {len(client_cert_header)})")
        
        try:
            decoded_cert = unquote(client_cert_header)
            client_cert_pem = decoded_cert.replace(" ", "\n")
            client_cert_pem = client_cert_pem.replace("-----BEGIN\nCERTIFICATE-----", "-----BEGIN CERTIFICATE-----")
            client_cert_pem = client_cert_pem.replace("-----END\nCERTIFICATE-----", "-----END CERTIFICATE-----")
            
            print(f"Decoded certificate (length: {len(client_cert_pem)})")
            
            validated_agent_id = validate_client_certificate(client_cert_pem)
            
            if not validated_agent_id:
                print("Certificate validation failed: certificate not found or does not match stored certificate")
                return False
            
            print(f"Client certificate validated successfully for agent: {validated_agent_id}")
            active_connections[validated_agent_id] = sid
            
        except Exception as e:
            print(f"Error processing client certificate: {str(e)}")
            return False
    else:
        print("Warning: No client certificate provided (development mode)")
    
    print(f"Socket.IO client connected: {sid}")


@sio.event
async def disconnect(sid):
    """
    Handle Socket.IO client disconnection.
    """
    agent_id = None
    for aid, session_id in active_connections.items():
        if session_id == sid:
            agent_id = aid
            break
    
    if agent_id:
        del active_connections[agent_id]
        print(f"Agent {agent_id} disconnected (session {sid})")
    else:
        print(f"Socket.IO client disconnected: {sid}")


@sio.event
async def heartbeat(sid, data):
    """
    Handle heartbeat events from orchestrator agents.
    """
    print(f"Heartbeat received from session {sid}: {data}")
    print(f"CPU: {data.get('cpu_usage')}, Memory: {data.get('memory_usage')}MB, Disk: {data.get('disk_usage')}MB")
    
    await sio.emit('heartbeat_ack', {'timestamp': datetime.now().isoformat()}, room=sid)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for orchestrator agents to connect using mTLS.
    This endpoint validates client certificates against stored certificates.
    
    For production with nginx:
    - Nginx should be configured to request client certificates
    - The client certificate is passed via X-SSL-Client-Cert header (percent-encoded)
    
    For local development:
    - Accepts connections without client certificate validation
    """
    client_cert_header = websocket.headers.get("X-SSL-Client-Cert", "")
    
    if client_cert_header:
        print(f"Received client certificate header (length: {len(client_cert_header)})")
        
        try:
            decoded_cert = unquote(client_cert_header)
            client_cert_pem = decoded_cert.replace(" ", "\n")
            client_cert_pem = client_cert_pem.replace("-----BEGIN\nCERTIFICATE-----", "-----BEGIN CERTIFICATE-----")
            client_cert_pem = client_cert_pem.replace("-----END\nCERTIFICATE-----", "-----END CERTIFICATE-----")
            
            print(f"Decoded certificate (length: {len(client_cert_pem)})")
            
            validated_agent_id = validate_client_certificate(client_cert_pem)
            
            if not validated_agent_id:
                print("Certificate validation failed: certificate not found or does not match stored certificate")
                await websocket.close(code=1008, reason="Invalid client certificate")
                return
            
            print(f"Client certificate validated successfully for agent: {validated_agent_id}")
        except Exception as e:
            print(f"Error processing client certificate: {str(e)}")
            await websocket.close(code=1008, reason="Certificate processing error")
            return
    else:
        print("Warning: No client certificate provided (development mode)")
    
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

# Wrap FastAPI app with Socket.IO ASGI app
socket_app = socketio.ASGIApp(sio, app)
