FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY viewpower_exporter.py .

EXPOSE 9199

ENTRYPOINT ["python", "viewpower_exporter.py"]

