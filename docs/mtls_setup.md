# mTLS Socket.IO Setup for Orchestrator Agents

This document describes how to configure mTLS (mutual TLS) for the Socket.IO endpoint that orchestrator agents use to connect to the API service.

## Architecture Overview

The mTLS implementation uses a hybrid approach:
- **Server Certificate**: Let's Encrypt certificate (trusted by clients by default)
- **Client Certificates**: Self-signed certificates uploaded via the `/agent/certificate` endpoint
- **Certificate Validation**: Application-level validation against stored certificates
- **Communication Protocol**: Socket.IO (not raw WebSocket)

This approach allows the orchestrator agents to use self-signed certificates while the server uses a trusted Let's Encrypt certificate.

## How It Works

1. **Certificate Upload**: The SaaS backend uploads agent certificates via `POST /agent/certificate`
2. **Certificate Storage**: Certificates are stored in `/var/orchestrator/certs` (configurable via `CERT_STORAGE_DIR`)
3. **Client Connection**: Orchestrator agents connect to `https://api.yourdomain.com` using Socket.IO client with their client certificate
4. **Socket.IO Handshake**: Socket.IO initiates HTTP polling at `/socket.io/` path, then upgrades to WebSocket
5. **Nginx Processing**: Nginx requests the client certificate and passes it to the backend via the `X-SSL-Client-Cert` header
6. **Application Validation**: The Socket.IO connect handler validates the client certificate against stored certificates
7. **Connection Established**: If validation succeeds (returns True), the Socket.IO connection is established; otherwise rejected (returns False)

## Nginx Configuration

Update your nginx configuration file (`/etc/nginx/conf.d/api.conf`) to include mTLS support for the WebSocket endpoint:

```nginx
server {
    listen 80;
    server_name api.yourdomain.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name api.yourdomain.com;
    
    # Let's Encrypt SSL certificates (managed by certbot)
    ssl_certificate /etc/letsencrypt/live/api.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.yourdomain.com/privkey.pem;
    
    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    
    # Client certificate configuration for Socket.IO endpoint
    # Request client certificate but don't require it (optional verification)
    # This allows the application to handle validation
    ssl_verify_client optional_no_ca;
    ssl_verify_depth 1;
    
    # Socket.IO endpoint with mTLS
    # Socket.IO uses /socket.io/ path for HTTP polling and WebSocket upgrade
    location /socket.io/ {
        proxy_pass http://unix:/home/ec2-user/api-service/api.sock;
        
        # WebSocket upgrade headers (Socket.IO upgrades from polling to WebSocket)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Standard proxy headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Pass client certificate to backend for validation
        proxy_set_header X-SSL-Client-Cert $ssl_client_escaped_cert;
        proxy_set_header X-SSL-Client-Verify $ssl_client_verify;
        
        # Socket.IO timeouts (long-lived connections)
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
        proxy_connect_timeout 86400;
    }
    
    # Regular HTTP endpoints (no client certificate required)
    location / {
        proxy_pass http://unix:/home/ec2-user/api-service/api.sock;
        include proxy_params;
    }
}
```

## Environment Configuration

Set the certificate storage directory in the systemd service file (`/etc/systemd/system/api.service`):

```ini
[Unit]
Description=Gunicorn service for OpenPLC API Service
After=network.target

[Service]
User=ec2-user
Group=ec2-user
WorkingDirectory=/home/ec2-user/api-service
Environment="PATH=/home/ec2-user/api-service/venv/bin"
Environment="API_KEY=your-secret-api-key"
Environment="CERT_STORAGE_DIR=/var/orchestrator/certs"
ExecStart=/home/ec2-user/api-service/venv/bin/gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b unix:/home/ec2-user/api-service/api.sock app.main:socket_app

[Install]
WantedBy=multi-user.target
```

## Setup Steps

### 1. Create Certificate Storage Directory

```bash
sudo mkdir -p /var/orchestrator/certs
sudo chown ec2-user:ec2-user /var/orchestrator/certs
sudo chmod 755 /var/orchestrator/certs
```

### 2. Update Nginx Configuration

```bash
sudo nano /etc/nginx/conf.d/api.conf
# Paste the configuration from above
```

### 3. Update Systemd Service

```bash
sudo nano /etc/systemd/system/api.service
# Add the CERT_STORAGE_DIR environment variable
```

### 4. Reload and Restart Services

```bash
# Test nginx configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx

# Reload systemd and restart API service
sudo systemctl daemon-reload
sudo systemctl restart api.service
```

### 5. Verify Setup

Check that the services are running:
```bash
sudo systemctl status nginx
sudo systemctl status api.service
```

## Testing mTLS Connection

### 1. Upload Agent Certificate

```bash
curl -X POST https://api.yourdomain.com/agent/certificate \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "07048933",
    "certificate": "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----"
  }'
```

### 2. Connect with Orchestrator Agent

The orchestrator agent should connect using Socket.IO:
- URL: `https://api.yourdomain.com` (Socket.IO handles the `/socket.io/` path automatically)
- Protocol: Socket.IO (not raw WebSocket)
- Client certificate: The self-signed certificate for the agent
- Client key: The private key for the agent

The agent's SSL session should be configured to:
- Use the client certificate and key
- Trust the Let's Encrypt CA (usually trusted by default)
- Pass the SSL session to the Socket.IO client via `http_session` parameter

## Troubleshooting

### Certificate Validation Fails

Check the application logs:
```bash
sudo journalctl -u api.service -f
```

Look for messages like:
- "Client certificate validated for agent: {agent_id}" (success)
- "Invalid client certificate" (validation failed)
- "Certificate validation error: ..." (parsing error)

### Socket.IO Connection Fails

1. Check nginx error logs:
   ```bash
   sudo tail -f /var/log/nginx/error.log
   ```

2. Verify the Socket.IO endpoint is accessible:
   ```bash
   curl -i https://api.yourdomain.com/socket.io/?EIO=4&transport=polling
   ```
   Should return a Socket.IO handshake response (not 403 or 404)

3. Check application logs for Socket.IO connection attempts:
   ```bash
   sudo journalctl -u api.service -f
   ```
   Look for: "Socket.IO connection attempt", "Client certificate validated successfully"

4. Verify systemd service is using `socket_app`:
   ```bash
   sudo systemctl cat api.service | grep ExecStart
   ```
   Should show `app.main:socket_app` (not `app.main:app`)

5. Check that the certificate storage directory exists and has correct permissions:
   ```bash
   ls -la /var/orchestrator/certs
   ```

### Client Certificate Not Passed to Backend

Verify nginx is passing the certificate:
```bash
# Add this to your nginx location block temporarily for debugging:
add_header X-Debug-SSL-Client-Cert $ssl_client_escaped_cert always;
```

## Security Considerations

1. **Certificate Storage**: Ensure `/var/orchestrator/certs` has appropriate permissions (755 for directory, 644 for certificate files)

2. **Certificate Validation**: The application validates that:
   - The client certificate matches a stored certificate exactly
   - The CN field in the certificate matches the stored agent ID

3. **Development Mode**: When no client certificate is provided (local development), the application logs a warning but allows the connection

4. **Production Mode**: In production, nginx should always request client certificates, and the application will reject connections without valid certificates

## Client Configuration (Orchestrator Agent)

The orchestrator agent should be configured with Socket.IO client and SSL session:

```python
import socketio
import ssl
import aiohttp

# Create SSL context for mTLS
ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
ssl_context.load_cert_chain(
    certfile="/path/to/agent/certificate.crt",
    keyfile="/path/to/agent/private.key"
)

# Create aiohttp session with SSL context
connector = aiohttp.TCPConnector(ssl=ssl_context)
session = aiohttp.ClientSession(connector=connector)

# Create Socket.IO client with SSL session
sio = socketio.AsyncClient(
    reconnection=True,
    reconnection_attempts=0,
    reconnection_delay=1,
    http_session=session
)

# Connect to Socket.IO server
await sio.connect("https://api.yourdomain.com")

# Emit events
await sio.emit("heartbeat", {
    "cpu_usage": 0.5,
    "memory_usage": 256,
    "disk_usage": 1024
})

# Handle events
@sio.on("heartbeat_ack")
async def on_heartbeat_ack(data):
    print(f"Heartbeat acknowledged: {data}")

# Wait for events
await sio.wait()
```

**Important Notes:**
- The agent uses Socket.IO client (not raw WebSocket)
- Connects via `https://` URL (Socket.IO handles `/socket.io/` path automatically)
- SSL session with client certificate is passed via `http_session` parameter
- The agent does not need to specify a CA certificate because Let's Encrypt certificates are trusted by default in most systems
- Socket.IO handles reconnection automatically with configurable retry logic
