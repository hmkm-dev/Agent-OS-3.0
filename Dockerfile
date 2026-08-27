FROM python:3.12.7-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY base_worker.py worker.py db.py ./
# Preserve the legacy top-level import context while supplying its canonical
# mission/evaluator implementations from the current source tree.
COPY mission ./mission
COPY services/mission ./services/mission
COPY services/hermes/evaluator ./evaluator
CMD ["python","worker.py"]
