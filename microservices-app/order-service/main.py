"""Order Service — Stub
This service will handle order processing.
Full implementation coming soon.
"""
from fastapi import FastAPI

app = FastAPI(
    title="Order Service",
    description="Order Processing Microservice — E-Commerce Platform (Stub)",
    version="0.1.0",
)

@app.get("/")
async def root():
    return {
        "service": "order-service",
        "status": "stub",
        "message": "Order Service — Coming Soon",
        "planned_endpoints": [
            "GET  /orders/",
            "POST /orders/",
            "GET  /orders/{id}",
            "PUT  /orders/{id}/status",
            "DELETE /orders/{id}",
        ]
    }

@app.get("/health")
async def health():
    return {"service": "order-service", "status": "stub"}
