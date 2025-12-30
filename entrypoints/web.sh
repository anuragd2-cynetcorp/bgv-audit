#!/bin/bash
set -e

# Start Gunicorn web server with proper logging
exec gunicorn \
    --bind 0.0.0.0:8080 \
    --workers 1 \
    --threads 8 \
    --timeout 0 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --capture-output \
    src.app:app

