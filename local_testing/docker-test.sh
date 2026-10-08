#!/bin/bash

# Build the image
docker image build -t stratasolar .

# Run the container
docker container run -p 8020:5000 -v $(pwd)/data:/data --rm stratasolar
