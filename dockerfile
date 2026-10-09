FROM python:3.12.4-slim-bookworm

# Resolve all Python requirements
COPY requirements.txt .
RUN pip install -r requirements.txt && rm requirements.txt

# Copy all required data to the container
COPY backend backend
COPY site site

# Make sure the main startup script is available
COPY supervisord.conf .

# Create and expose data folder in the container
VOLUME ["/data"]

# Expose port 5000 for the webserver
EXPOSE 5000

# Fixes an issue with Python prints being swallowed
ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=4)"

# Runs as root so bind-mounted /data keeps typical NAS volume permissions.
ENTRYPOINT ["supervisord"]
