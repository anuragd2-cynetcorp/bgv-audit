#!/bin/bash
set -e

# Write secrets to files
if [ -n "$FIREBASE_AUTH_JSON" ]; then
    echo "$FIREBASE_AUTH_JSON" > /app/firebase_auth.json
    export GOOGLE_APPLICATION_CREDENTIALS=/app/firebase_auth.json
fi

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

