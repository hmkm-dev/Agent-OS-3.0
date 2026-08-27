FROM python:3.12.7-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY base_worker.py .
COPY worker.py .
COPY agent_os30 ./agent_os30
CMD ["python","worker.py"]
