FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./steering-server/

WORKDIR /app/steering-server

RUN mkdir -p /app/logs/raw_data

EXPOSE 30500

CMD ["python", "src/app.py", "--strategy", "ucb1", "--gateway_mode"]
