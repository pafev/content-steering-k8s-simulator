FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
EXPOSE 30500
CMD ["gunicorn", "--chdir", "src", "--bind", "0.0.0.0:30500", "--workers", "2", "--threads", "4", "--access-logfile", "-", "app:app"]
