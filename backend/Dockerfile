FROM python:3.11-slim

WORKDIR /app

# Dependencies first so edits to the source do not invalidate the layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# clinic.json is read on every request; data/ also holds the conversation log.
RUN mkdir -p data .cache

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
