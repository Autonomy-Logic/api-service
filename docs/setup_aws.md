# AWS Setup Instructions
This document provides step-by-step instructions for setting up the application on an EC2 AWS instance.

## Prerequisites
- An AWS account with permissions to create and manage EC2 instances.
- Basic knowledge of AWS services and Linux command line.
- SSH client to connect to the EC2 instance.

## Step 1: Install api-service and test locally on your EC2 instance
1. Clone the repository:
   ```bash
   git clone https://github.com/autonomy-logic/api-service.git
   ```
2. Navigate to the project directory:
   ```bash
   cd api-service
   ```
3. Install:
   ```bash
   sudo ./install.sh
   ```
4. Create API_KEY environment variable:
    ```bash
    export API_KEY="supersecretkey"
    ```
5. Run the application locally:
   ```bash
   start_local.sh
   ```
6. Test the application using curl:
    ```bash
    curl -X POST http://localhost:8000/hello-world \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer supersecretkey" \
    -d '{"name": "James"}'
    ```
    Make sure to replace `supersecretkey` with your actual API key.

## Step 2: Configure gunicorn + nginx
1. Create a systemd service file for gunicorn:
    ```bash
    sudo nano /etc/systemd/system/api.service
    ```
    Add the following content:
    ```ini
    [Unit]
    Description=Gunicorn service for OpenPLC API Service
    After=network.target

    [Service]
    User=ec2-user
    Group=ec2-user
    WorkingDirectory=/home/ec2-user/api-service
    Environment="PATH=/home/ec2-user/api-service/venv/bin"
    Environment="API_KEY=supersecretkey"
    ExecStart=/home/ec2-user/api-service/venv/bin/gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b unix:/home/ec2-user/api-service/api.sock app.main:app

    [Install]
    WantedBy=multi-user.target
    ```

    Note: Make sure to replace `supersecretkey` with your actual API key.

2. Reload systemd and start the service:
    ```bash
    sudo systemctl daemon-reload
    sudo systemctl start api.service
    sudo systemctl enable api.service
    ```

3. Configure nginx as a reverse proxy:
    ```bash
    sudo nano /etc/nginx/conf.d/api.conf
    ```
    Add the following content:
    ```nginx
    server {
        listen 80;
        server_name api.getedge.me;

        location / {
            proxy_pass http://unix:/home/ec2-user/api-service/api.sock:;
            include proxy_params;
        }
    }
    ```

4. Make sure nginx can access gunicorn socket:
    ```bash
    sudo chmod 666 /home/ec2-user/api-service/api.sock
    sudo chmod 755 /home
    sudo chmod 755 /home/ec2-user
    sudo chmod 755 /home/ec2-user/api-service
    ```

5. Test nginx configuration and restart nginx:
    ```bash
    sudo nginx -t
    sudo systemctl restart nginx
    ```

    Note: Make sure your EC2 instance's security group allows inbound traffic on port 80 (HTTP) to access the application from the internet.

6. Configure Domain
    - Go to the domain registrar's website
    - Create the following DNS record:
        - Type: A
        - Name: @
        - Value: [Your EC2 Instance Public IP]
        - TTL: 1 Hour
    - Create another DNS record:
        - Type: CNAME
        - Name: api
        - Value: [Your EC2 Instance Public IP]
        - TTL: 1 Hour

## Step 3: Secure the application with SSL
1. Install Certbot:
    ```bash
    sudo yum install certbot python3-certbot-nginx -y
    ```

2. Obtain and install SSL certificate:
    ```bash
    sudo certbot --nginx -d [your_domain] -d api.[your_domain]
    ```

3. Follow the prompts to complete the SSL installation. Certbot will automatically configure nginx to use the new certificates.