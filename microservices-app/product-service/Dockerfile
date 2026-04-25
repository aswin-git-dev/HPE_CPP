# ─── Stage 1: Base ───────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

WORKDIR /app

# Copy and install Python deps (wheels only — no apt)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ─── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Create non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Copy installed packages from base
COPY --from=base /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=base /usr/local/bin /usr/local/bin

# Copy application source
COPY main.py .

# Switch to non-root user
USER appuser

# Expose service port
EXPOSE 8001

# Start server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
