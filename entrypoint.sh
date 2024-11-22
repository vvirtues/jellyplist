#!/bin/sh

# Exit immediately if a command exits with a non-zero status
set -e

# Function to wait for a service to be ready
wait_for_service() {
    local host="$1"
    local port="$2"
    local retries=30
    local wait=2

    until nc -z "$host" "$port" || [ "$retries" -eq 0 ]; do
        echo "Waiting for $host:$port..."
        sleep "$wait"
        retries=$((retries - 1))
    done

    if [ "$retries" -eq 0 ]; then
        echo "Service $host:$port is not available after waiting."
        exit 1
    fi
}

# Ensure the required environment variable is set
if [ -z "$JELLYPLIST_DB_HOST" ]; then
    echo "Environment variable JELLYPLIST_DB_HOST is not set. Exiting."
    exit 1
fi

# Wait for PostgreSQL to be ready using the environment variable
wait_for_service "$JELLYPLIST_DB_HOST" 5432

# Apply database migrations
echo "Applying database migrations..."
flask db upgrade

# Start the Flask application
echo "Starting Flask application..."
exec "$@"
