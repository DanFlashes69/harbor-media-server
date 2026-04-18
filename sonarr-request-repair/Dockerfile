FROM python:3.12-alpine

WORKDIR /app

RUN pip install --no-cache-dir requests

COPY repair.py /app/repair.py

CMD ["python", "-u", "/app/repair.py"]
