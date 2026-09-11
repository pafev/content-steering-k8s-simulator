FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY gunicorn.conf.py .
EXPOSE 30600 9000/udp
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
