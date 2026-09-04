FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mindtrail/ mindtrail/
COPY eval/ eval/

# Memory lives here, outside the image layer, so it survives container
# restarts when this path is bind-mounted at `docker run` time.
ENV MINDTRAIL_CHROMA_DIR=/data/chroma_data
VOLUME ["/data"]

EXPOSE 8765

# 0.0.0.0 is required inside a container: binding loopback would make the
# server invisible to Docker's port mapping even with -p published.
CMD ["python", "-m", "mindtrail.cli", "chat", "--no-open", "--host", "0.0.0.0"]
