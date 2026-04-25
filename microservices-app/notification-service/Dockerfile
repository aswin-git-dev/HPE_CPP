# Use Python 3.11 slim image
FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY main.py .

# Switch to non-root user
USER appuser

EXPOSE 8004

# Run the FastAPI app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]