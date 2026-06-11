FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY api/ api/
COPY cynda_agent/ cynda_agent/

EXPOSE 3000

RUN adduser --disabled-password --gecos "" appuser
USER appuser

CMD ["sh", "-c", "uvicorn api.index:app --host 0.0.0.0 --port ${PORT:-3000}"]
