#!/bin/bash

# Check for root privileges
check_root() 
{
    if [[ $EUID -ne 0 ]]; then
        echo "ERROR: This script must be run as root" >&2
        echo "Example: sudo ./install.sh" >&2
        exit 1
    fi
}

# Make sure we are root before proceeding
check_root

# Install required packages (Amazon Linux)
python3 -m venv venv
source venv/bin/activate
wget https://bootstrap.pypa.io/get-pip.py
python get-pip.py
python -m pip install -r requirements.txt
deactivate

# Install nginx
yum install -y nginx -y
systemctl enable nginx
systemctl start nginx
