#!/bin/bash
set -e

# Start Gunicorn web server
exec gunicorn \
    --bind 0.0.0.0:8080 \
    --workers 1 \
    --threads 8 \
    --timeout 0 \
    src.app:app

