# mTLS WebSocket Setup for Orchestrator Agents

This document describes how to configure mTLS (mutual TLS) for the WebSocket endpoint that orchestrator agents use to connect to the API service.

## Architecture Overview

The mTLS implementation uses a hybrid approach:
- **Server Certificate**: Let's Encrypt certificate (trusted by clients by default)
- **Client Certificates**: Self-signed certificates uploaded via the `/agent/certificate` endpoint
- **Certificate Validation**: Application-level validation against stored certificates

This approach allows the orchestrator agents to use self-signed certificates while the server uses a trusted Let's Encrypt certificate.

## How It Works

1. **Certificate Upload**: The SaaS backend uploads agent certificates via `POST /agent/certificate`
2. **Certificate Storage**: Certificates are stored in `/var/orchestrator/certs` (configurable via `CERT_STORAGE_DIR`)
3. **Client Connection**: Orchestrator agents connect to `wss://api.yourdomain.com/ws` with their client certificate
4. **Nginx Processing**: Nginx requests the client certificate and passes it to the backend via the `X-SSL-Client-Cert` header
5. **Application Validation**: The FastAPI application validates the client certificate against stored certificates
6. **Connection Established**: If validation succeeds, the WebSocket connection is established

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
    
    # Client certificate configuration for WebSocket endpoint
    # Request client certificate but don't require it (optional verification)
    # This allows the application to handle validation
    ssl_verify_client optional_no_ca;
    ssl_verify_depth 1;
    
    # WebSocket endpoint with mTLS
    location /ws {
        proxy_pass http://unix:/home/ec2-user/api-service/api.sock;
        
        # WebSocket upgrade headers
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
        
        # WebSocket timeouts
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
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
ExecStart=/home/ec2-user/api-service/venv/bin/gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b unix:/home/ec2-user/api-service/api.sock app.main:app

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

The orchestrator agent should connect using:
- URL: `wss://api.yourdomain.com/ws`
- Client certificate: The self-signed certificate for the agent
- Client key: The private key for the agent

The agent's SSL context should be configured to:
- Use the client certificate and key
- Trust the Let's Encrypt CA (usually trusted by default)

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

### WebSocket Connection Fails

1. Check nginx error logs:
   ```bash
   sudo tail -f /var/log/nginx/error.log
   ```

2. Verify the WebSocket upgrade is working:
   ```bash
   curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" \
     -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: test" \
     https://api.yourdomain.com/ws
   ```

3. Check that the certificate storage directory exists and has correct permissions:
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

The orchestrator agent should be configured with:

```python
import ssl
import websockets

# SSL context for mTLS
ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
ssl_context.load_cert_chain(
    certfile="/path/to/agent/certificate.crt",
    keyfile="/path/to/agent/private.key"
)

# Connect to WebSocket with mTLS
async with websockets.connect(
    "wss://api.yourdomain.com/ws",
    ssl=ssl_context
) as websocket:
    # Send/receive messages
    pass
```

The agent does not need to specify a CA certificate because Let's Encrypt certificates are trusted by default in most systems.
