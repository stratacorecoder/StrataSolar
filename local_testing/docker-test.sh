cd "$(dirname "$0")/.."

echo "Building Docker image"
docker image build -t stratasolar .

echo "Running Docker image"
docker container run -p 8020:5000 -v $(pwd)/data:/data --rm stratasolar

echo "Cleaning up"
echo y | docker image prune
echo y | docker volume prune
