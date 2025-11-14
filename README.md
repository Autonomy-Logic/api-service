# API Service

Backend API service for the OpenPLC Orchestrator system. This service acts as a middle layer between the SaaS application backend and orchestrator agents, providing secure communication channels and certificate management.

## Overview

The API Service provides:
- **Certificate Management**: Upload and store agent certificates for mTLS authentication
- **Socket.IO Communication**: Secure Socket.IO endpoint for orchestrator agents to connect and exchange messages
- **Authentication**: API key-based authentication for SaaS backend requests
- **mTLS Support**: Mutual TLS authentication for orchestrator agent connections

## Architecture

```
SaaS Backend → HTTPS/API Key → API Service → Socket.IO/mTLS → Orchestrator Agents
```

The service uses:
- **FastAPI** for the web framework
- **Socket.IO** for real-time bidirectional communication with agents
- **Uvicorn** as the ASGI server (development)
- **Gunicorn + Uvicorn** for production deployment
- **Nginx** as reverse proxy with SSL termination (production)
- **Let's Encrypt** for server-side SSL certificates

## API Endpoints

### 1. POST /hello-world

Test endpoint to verify API service is running.

**Request:**
```bash
curl -X POST http://localhost:8000/hello-world \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test"}'
```

**Response:**
```json
{
  "message": "Hello, Test!"
}
```

**Authentication:** Required (Bearer token)

### 2. POST /agent/certificate

Upload an agent certificate for mTLS authentication. The agent ID must match the CN (Common Name) field in the certificate.

**Request:**
```bash
curl -X POST https://api.yourdomain.com/agent/certificate \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "07048933",
    "certificate": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"
  }'
```

**Request Body:**
- `agent_id` (string, required): The unique identifier for the agent
- `certificate` (string, required): PEM-encoded certificate

**Response (Success):**
```json
{
  "message": "Certificate uploaded successfully",
  "agent_id": "07048933"
}
```

**Response (Error - CN Mismatch):**
```json
{
  "detail": "Agent ID mismatch: provided '07048933' but certificate CN is '12345678'"
}
```

**Authentication:** Required (Bearer token)

**Validation:**
- Extracts CN from certificate subject field
- Verifies agent_id matches the CN exactly
- Stores certificate in configured directory

### 3. Socket.IO Connection

Socket.IO endpoint for orchestrator agents to connect using mTLS. Agents send heartbeat messages and receive commands via event-based communication.

**Connection:**
```python
import socketio
import asyncio

# Create Socket.IO client with SSL session
sio = socketio.AsyncClient(
    reconnection=True,
    reconnection_attempts=0,
    reconnection_delay=1,
    http_session=get_ssl_session()  # SSL session with client certificate
)

# Connect to server
await sio.connect("https://api.yourdomain.com")

# Emit heartbeat event
await sio.emit("heartbeat", {
    "cpu_usage": 0.5,
    "memory_usage": 256,
    "disk_usage": 1024,
    "timestamp": "2025-11-13T12:00:00"
})

# Handle heartbeat acknowledgment
@sio.on("heartbeat_ack")
async def on_heartbeat_ack(data):
    print(f"Heartbeat acknowledged: {data}")

# Wait for events
await sio.wait()
```

**Protocol Details:**
- Socket.IO uses HTTP polling initially at `/socket.io/` path
- Upgrades to WebSocket after successful handshake
- Event-based messaging (emit/on) instead of raw messages
- Automatic reconnection with configurable retry logic

**Supported Events:**
- `connect`: Triggered when connection is established
- `disconnect`: Triggered when connection is closed
- `heartbeat`: Agent emits system status information
- `heartbeat_ack`: Server acknowledges heartbeat

**Authentication:** 
- Production: Client certificate validated against stored certificates during Socket.IO connect event
- Development: No certificate validation (logs warning)

**Certificate Validation:**
- Nginx passes client certificate via `X-SSL-Client-Cert` header
- Application validates certificate in Socket.IO connect handler
- Connection rejected (returns False) if certificate is invalid or not found
- Agent must present valid client certificate during TLS handshake

## Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `API_KEY` | Secret key for API authentication | - | Yes |
| `CERT_STORAGE_DIR` | Directory for storing agent certificates | `./certs` | No |

## Local Development

### Prerequisites
- Python 3.12+
- pip

### Setup

1. Clone the repository:
```bash
git clone https://github.com/Autonomy-Logic/api-service.git
cd api-service
```

2. Create virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Set environment variables:
```bash
export API_KEY="your-secret-api-key"
```

4. Run the development server:
```bash
./start_local.sh
```

The API will be available at `http://localhost:8000`.

### Testing

Test the hello-world endpoint:
```bash
curl -X POST http://localhost:8000/hello-world \
  -H "Authorization: Bearer your-secret-api-key" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test"}'
```

Test certificate upload:
```bash
curl -X POST http://localhost:8000/agent/certificate \
  -H "Authorization: Bearer your-secret-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "test123",
    "certificate": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"
  }'
```

Test Socket.IO connection:
```python
import asyncio
import socketio

async def test_socketio():
    sio = socketio.AsyncClient()
    
    @sio.on('heartbeat_ack')
    async def on_heartbeat_ack(data):
        print(f"Heartbeat acknowledged: {data}")
        await sio.disconnect()
    
    await sio.connect("http://localhost:8000")
    await sio.emit("heartbeat", {
        "cpu_usage": 0.5,
        "memory_usage": 256,
        "disk_usage": 1024
    })
    await sio.wait()

asyncio.run(test_socketio())
```

## Production Deployment

For production deployment on AWS EC2 with nginx and Let's Encrypt SSL, see the detailed setup guides:

- **[AWS Setup Instructions](docs/setup_aws.md)**: Complete guide for deploying to EC2 with nginx, gunicorn, and Let's Encrypt
- **[mTLS Setup Guide](docs/mtls_setup.md)**: Comprehensive guide for configuring mTLS authentication for WebSocket connections

### Important: Socket.IO Single-Worker Requirement

**⚠️ CRITICAL: Socket.IO requires running with a single gunicorn worker** to maintain session affinity during the HTTP polling → WebSocket upgrade process. Multiple workers will cause "Invalid session" errors because the upgrade request may hit a different worker than the one that created the session.

**Systemd service configuration:**
```ini
ExecStart=/path/to/venv/bin/gunicorn -w 1 -k uvicorn.workers.UvicornWorker -b unix:/path/to/api.sock app.main:socket_app
```

**Key points:**
- Use `-w 1` (single worker) for Socket.IO
- Use `app.main:socket_app` (not `app.main:app`)
- For horizontal scaling, run multiple instances behind a load balancer with sticky sessions
- Add Redis manager for cross-instance broadcasting when scaling horizontally

### Quick Production Setup

1. Install and configure the service:
```bash
sudo ./install.sh
```

2. Configure systemd service with environment variables and **single worker (-w 1)**:
```bash
sudo nano /etc/systemd/system/api.service
# Ensure: -w 1 and app.main:socket_app
```

3. Configure nginx as reverse proxy:
```bash
sudo nano /etc/nginx/conf.d/api.conf
```

4. Install SSL certificates:
```bash
sudo certbot --nginx -d yourdomain.com -d api.yourdomain.com
```

5. Start services:
```bash
sudo systemctl daemon-reload
sudo systemctl start api.service
sudo systemctl enable api.service
sudo systemctl reload nginx
```

See [docs/setup_aws.md](docs/setup_aws.md) for detailed instructions.

## mTLS Configuration

The WebSocket endpoint supports mutual TLS authentication for secure agent connections. The implementation uses a hybrid approach:

- **Server Certificate**: Let's Encrypt (trusted by default)
- **Client Certificates**: Self-signed certificates validated against stored certificates
- **Certificate Validation**: Application-level validation

### Setup Steps

1. Upload agent certificates via the `/agent/certificate` endpoint
2. Configure nginx to request client certificates (see [docs/mtls_setup.md](docs/mtls_setup.md))
3. Agents connect with their client certificates
4. Server validates certificates against stored certificates

See [docs/mtls_setup.md](docs/mtls_setup.md) for complete mTLS setup instructions, nginx configuration, and troubleshooting.

## Project Structure

```
api-service/
├── app/
│   └── main.py              # FastAPI application
├── docs/
│   ├── setup_aws.md         # AWS deployment guide
│   └── mtls_setup.md        # mTLS configuration guide
├── venv/                    # Python virtual environment
├── install.sh               # Installation script
├── start_local.sh           # Local development startup script
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## Dependencies

- **fastapi**: Modern web framework for building APIs
- **uvicorn[standard]**: ASGI server with WebSocket support
- **gunicorn**: Production WSGI/ASGI server
- **python-multipart**: Form and file upload support
- **cryptography**: Certificate parsing and validation
- **websockets**: WebSocket protocol implementation (legacy, kept for compatibility)
- **python-socketio**: Socket.IO server implementation for real-time communication

## Security

### Authentication
- All HTTP endpoints require Bearer token authentication via `Authorization` header
- API key must be set via `API_KEY` environment variable
- Invalid or missing API keys return 403 Forbidden

### mTLS for WebSocket
- Client certificates validated against stored certificates
- Certificate CN must match agent ID
- Invalid certificates rejected with WebSocket close code 1008
- Development mode allows connections without certificates (logs warning)

### CORS Policy
- Restricted to specific origins (autonomy-edge.com, localhost)
- Only POST and OPTIONS methods allowed
- Preflight requests cached for 24 hours

### Certificate Storage
- Certificates stored in configurable directory
- Production: `/var/orchestrator/certs` (requires proper permissions)
- Development: `./certs` (local directory)
- Certificates should be readable only by the application user

## Troubleshooting

### API Service Won't Start
- Check that `API_KEY` environment variable is set
- Verify virtual environment is activated
- Check logs: `sudo journalctl -u api.service -f`

### Certificate Upload Fails
- Verify certificate is in valid PEM format
- Check that CN field exists in certificate
- Ensure agent_id matches CN exactly
- Verify `CERT_STORAGE_DIR` has correct permissions

### Socket.IO Connection Fails
- **"Invalid session" errors**: This means multiple gunicorn workers are running. Change to `-w 1` in systemd service, run `sudo systemctl daemon-reload`, then `sudo systemctl restart api.service`
- Check nginx configuration has `/socket.io/` location block with WebSocket upgrade headers
- Verify client certificate is valid and uploaded
- Check application logs for certificate validation errors: `sudo journalctl -u api.service -f`
- Ensure nginx is passing `X-SSL-Client-Cert` header
- Verify systemd service is using `app.main:socket_app` (not `app.main:app`)
- Check that orchestrator-agent is using Socket.IO client (not raw WebSocket)

### mTLS Not Working
- Verify nginx is requesting client certificates (`ssl_verify_client optional_no_ca`)
- Check that client certificate is being passed to backend
- Verify certificate storage directory exists and has correct permissions
- Ensure `/socket.io/` location block includes `proxy_set_header X-SSL-Client-Cert $ssl_client_escaped_cert`
- See [docs/mtls_setup.md](docs/mtls_setup.md) for detailed troubleshooting

## Contributing

1. Create a feature branch from `main`
2. Make your changes
3. Test locally using `./start_local.sh`
4. Create a pull request

## License

Copyright © 2025 Autonomy Logic. All rights reserved.

## Support

For issues or questions, please contact the development team or create an issue in the repository
