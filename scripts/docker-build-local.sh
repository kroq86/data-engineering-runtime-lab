#!/usr/bin/env bash
# Build the MCP server Docker image locally (use this instead of pulling from GitHub).
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
IMAGE_NAME="${1:-mini-data-engine:local}"
echo "Building $IMAGE_NAME from $ROOT ..."
docker build -t "$IMAGE_NAME" .
echo "Done. Run MCP with local image: $IMAGE_NAME"
echo "Example Cursor config: .cursor/mcp.docker.local.json (set workspaceFolder to your project, e.g. threads)"
