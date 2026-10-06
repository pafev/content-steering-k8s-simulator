FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

RUN pip install --no-cache-dir playwright==1.63.0
COPY index.html /app/index.html
COPY assets /app/assets
COPY client.py /app/client.py
CMD ["python", "/app/client.py"]
