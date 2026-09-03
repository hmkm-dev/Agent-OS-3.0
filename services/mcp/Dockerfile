FROM python:3.14.7-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8100

CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8100"]
