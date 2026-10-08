#!/bin/bash
cd "$(dirname "$0")/.." || exit 1

echo "Building Docker image"
docker image build -t stratasolar .

echo "Running Docker image"
docker container run -p 8020:5000 -v $(pwd)/data:/data --rm stratasolar
