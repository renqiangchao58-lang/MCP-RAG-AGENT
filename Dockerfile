FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY data ./data
COPY evaluations ./evaluations

EXPOSE 8000 8001 8501

CMD ["python", "-m", "support_pilot.api"]

