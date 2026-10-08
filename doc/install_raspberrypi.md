# Installation Instructions: Raspberry Pi 3

## Prerequisites

Make sure Docker is installed on your Raspberry Pi:

```sh
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

Log out and back in for the group change to take effect.

## Clone the Repository

```sh
git clone https://github.com/stratacorecoder/StrataSolar.git
cd StrataSolar
```

## Build the Docker Image

Build the image directly on the Pi (it will automatically target the native ARM architecture):

```sh
docker build -t stratasolar .
```

## Run the Container

```sh
docker run -d \
  --name stratasolar \
  --restart always \
  -p 8020:5000 \
  -v $(pwd)/data:/data \
  stratasolar
```

The web interface is then available at `http://<raspberry-pi-ip>:8020`.

## Configuration

Copy the config template and edit it to match your setup:

```sh
mkdir -p data
cp templates/config.yml data/config.yml
nano data/config.yml
```
