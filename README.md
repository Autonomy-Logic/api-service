# API Service

Backend API service for the OpenPLC Orchestrator system. This service acts as a middle layer between the SaaS application backend and orchestrator agents, providing secure communication channels and certificate management.

## Overview

The API Service provides:
- **Certificate Management**: Upload and store agent certificates for mTLS authentication
- **WebSocket Communication**: Secure WebSocket endpoint for orchestrator agents to connect and exchange messages
- **Authentication**: API key-based authentication for SaaS backend requests
- **mTLS Support**: Mutual TLS authentication for orchestrator agent connections

## Architecture

```
SaaS Backend → HTTPS/API Key → API Service → WebSocket/mTLS → Orchestrator Agents
```

The service uses:
- **FastAPI** for the web framework
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

### 3. WebSocket /ws

WebSocket endpoint for orchestrator agents to connect using mTLS. Agents send heartbeat messages and receive commands.

**Connection:**
```python
import websockets
import ssl

ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
ssl_context.load_cert_chain(
    certfile="/path/to/agent/certificate.crt",
    keyfile="/path/to/agent/private.key"
)

async with websockets.connect(
    "wss://api.yourdomain.com/ws",
    ssl=ssl_context
) as websocket:
    # Send heartbeat
    await websocket.send(json.dumps({
        "topic": "heartbeat",
        "payload": {
            "id": "07048933",
            "cpu_usage": 0.5,
            "memory_usage": 256,
            "disk_usage": 1024,
            "timestamp": "2025-11-13T12:00:00"
        }
    }))
    
    # Receive response
    response = await websocket.recv()
```

**Message Format:**
All messages use JSON with a topic-based routing system:
```json
{
  "topic": "message_type",
  "payload": {
    "key": "value"
  }
}
```

**Supported Topics:**
- `heartbeat`: Agent sends system status information
- `heartbeat_ack`: Server acknowledges heartbeat

**Authentication:** 
- Production: Client certificate validated against stored certificates
- Development: No certificate validation (logs warning)

**Certificate Validation:**
- Nginx passes client certificate via `X-SSL-Client-Cert` header
- Application validates certificate against stored certificates
- Connection rejected if certificate is invalid or not found

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

Test WebSocket connection:
```python
import asyncio
import websockets
import json

async def test_websocket():
    async with websockets.connect("ws://localhost:8000/ws") as ws:
        await ws.send(json.dumps({
            "topic": "heartbeat",
            "payload": {"id": "test123", "cpu_usage": 0.5}
        }))
        response = await ws.recv()
        print(response)

asyncio.run(test_websocket())
```

## Production Deployment

For production deployment on AWS EC2 with nginx and Let's Encrypt SSL, see the detailed setup guides:

- **[AWS Setup Instructions](docs/setup_aws.md)**: Complete guide for deploying to EC2 with nginx, gunicorn, and Let's Encrypt
- **[mTLS Setup Guide](docs/mtls_setup.md)**: Comprehensive guide for configuring mTLS authentication for WebSocket connections

### Quick Production Setup

1. Install and configure the service:
```bash
sudo ./install.sh
```

2. Configure systemd service with environment variables:
```bash
sudo nano /etc/systemd/system/api.service
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
- **websockets**: WebSocket protocol implementation

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

### WebSocket Connection Fails
- Check nginx configuration for WebSocket upgrade headers
- Verify client certificate is valid and uploaded
- Check application logs for certificate validation errors
- Ensure nginx is passing `X-SSL-Client-Cert` header

### mTLS Not Working
- Verify nginx is requesting client certificates (`ssl_verify_client optional_no_ca`)
- Check that client certificate is being passed to backend
- Verify certificate storage directory exists and has correct permissions
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
