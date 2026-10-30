FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

# tzdata so the API's "last N hours" cutoff uses the right local time
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pycampbellcr1000 pyserial

WORKDIR /app
COPY collector.py api.py ./

# default command (overridden per-service in docker-compose)
CMD ["python", "collector.py"]
