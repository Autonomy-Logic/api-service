#!/bin/bash
source venv/bin/activate
uvicorn app.main:socket_app --host 0.0.0.0 --port 8000
deactivate
