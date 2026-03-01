"""Product Service — Stub
This service will handle the product catalog.
Full implementation coming soon.
"""
from fastapi import FastAPI

app = FastAPI(
    title="Product Service",
    description="Product Catalog Microservice — E-Commerce Platform (Stub)",
    version="0.1.0",
)

@app.get("/")
async def root():
    return {
        "service": "product-service",
        "status": "stub",
        "message": "Product Service — Coming Soon",
        "planned_endpoints": [
            "GET  /products/",
            "POST /products/",
            "GET  /products/{id}",
            "PUT  /products/{id}",
            "DELETE /products/{id}",
        ]
    }

@app.get("/health")
async def health():
    return {"service": "product-service", "status": "stub"}
