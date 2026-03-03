"""
Payment Service — Functional Version
Handles payment initiation, status check, and refund.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict
import uuid

app = FastAPI(
    title="Payment Service",
    description="Payment Handling Microservice — E-Commerce Platform",
    version="1.0.0",
)

# In-memory storage (temporary database)
payments: Dict[str, dict] = {}


# -----------------------------
# Request Models
# -----------------------------
class PaymentRequest(BaseModel):
    order_id: str
    amount: float
    method: str


# -----------------------------
# Root Endpoint
# -----------------------------
@app.get("/")
async def root():
    return {
        "service": "payment-service",
        "status": "running",
        "message": "Payment Service is Active"
    }


# -----------------------------
# Health Check
# -----------------------------
@app.get("/health")
async def health():
    return {"service": "payment-service", "status": "healthy"}


# -----------------------------
# Initiate Payment
# -----------------------------
@app.post("/payments/initiate")
async def initiate_payment(payment: PaymentRequest):
    payment_id = str(uuid.uuid4())

    payments[payment_id] = {
        "order_id": payment.order_id,
        "amount": payment.amount,
        "method": payment.method,
        "status": "SUCCESS"
    }

    return {
        "payment_id": payment_id,
        "status": "SUCCESS",
        "message": "Payment processed successfully"
    }


# -----------------------------
# Check Payment Status
# -----------------------------
@app.get("/payments/{payment_id}/status")
async def payment_status(payment_id: str):
    if payment_id not in payments:
        raise HTTPException(status_code=404, detail="Payment not found")

    return {
        "payment_id": payment_id,
        "status": payments[payment_id]["status"]
    }


# -----------------------------
# Refund Payment
# -----------------------------
@app.post("/payments/{payment_id}/refund")
async def refund_payment(payment_id: str):
    if payment_id not in payments:
        raise HTTPException(status_code=404, detail="Payment not found")

    payments[payment_id]["status"] = "REFUNDED"

    return {
        "payment_id": payment_id,
        "status": "REFUNDED",
        "message": "Payment refunded successfully"
    }