
#!/bin/bash
#
# deploy.sh: Canonical deployment script for the Trading Engine Services stack.
#
# This script orchestrates the deployment of the refactored microservices
# by pulling versioned Docker images, running database migrations, and
# restarting the services. It is designed to be idempotent and robust.
#
# USAGE: sudo sh /srv/apps/trading-engine-services/deploy.sh

# Stop execution if any command fails.
set -e

# --- Configuration Variables ---
# The Docker Compose file defining the new microservice stack.
DOCKER_COMPOSE_FILE="/srv/apps/trading-engine-services/docker-compose.yml"
# The private container registry URL.
PRIVATE_REGISTRY_URL="ghcr.io/your-organization"
# Path to registry credentials.
REGISTRY_USER_FILE="/opt/secrets/registry_user.txt"
REGISTRY_TOKEN_FILE="/opt/secrets/registry_token.txt"

echo "--- [Step 1/6] Authenticating with Private Docker Registry ---"
if [ -f "$REGISTRY_USER_FILE" ] && [ -f "$REGISTRY_TOKEN_FILE" ]; then
    cat "$REGISTRY_TOKEN_FILE" | docker login "$PRIVATE_REGISTRY_URL" --username $(cat "$REGISTRY_USER_FILE") --password-stdin
    echo "Docker registry authentication successful."
else
    echo "Error: Registry credential files not found. Halting deployment."
    exit 1
fi
echo ""

echo "--- [Step 2/6] Pulling latest service images ---"
# Pulls all images defined in the compose file with versioned tags.
docker compose -f "$DOCKER_COMPOSE_FILE" pull
echo "Latest images pulled successfully."
echo ""

echo "--- [Step 3/6] Stopping and removing old service containers ---"
# Ensures a clean state before starting new containers.
docker compose -f "$DOCKER_COMPOSE_FILE" down
echo "Old containers stopped and removed."
echo ""

echo "--- [Step 4/6] Applying database migrations to OCI ---"
# This is the implementation of the directive from Epic 1.2.
# It runs the 'migrator' service as a one-off task to apply the schema changes.
# The '--rm' flag ensures the container is removed after the task completes.
docker compose -f "$DOCKER_COMPOSE_FILE" run --rm migrator alembic upgrade head
echo "Database schema is now up to date."
echo ""

echo "--- [Step 5/6] Starting the new service stack ---"
# Starts all services in detached mode.
docker compose -f "$DOCKER_COMPOSE_FILE" up -d
echo "All services have been started."
echo ""

echo "--- [Step 6/6] Cleaning up unused Docker images ---"
# Frees up disk space by removing dangling or old images.
docker image prune -f
echo "Docker image cleanup complete."
echo ""

echo "======================================================"
echo "✅ DEPLOYMENT COMPLETE"
echo "The Trading Engine Services stack has been deployed."
echo "======================================================"