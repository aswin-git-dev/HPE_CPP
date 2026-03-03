from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pymongo import MongoClient
from bson import ObjectId
import os
from typing import List

app = FastAPI(
    title="Order Service",
    description="Order Processing Microservice — E-Commerce Platform",
    version="1.0.0",
)

# ─── Database Configuration ────────────────────────────────────────────────
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "orderdb")

client = MongoClient(MONGO_URL)
db = client[DB_NAME]
orders_collection = db["orders"]


# ─── Models ─────────────────────────────────────────────────────────────────
class OrderCreate(BaseModel):
    user_id: str
    product_id: str
    quantity: int = Field(..., gt=0)


class OrderResponse(BaseModel):
    id: str
    user_id: str
    product_id: str
    quantity: int
    status: str


# ─── Utility Function ───────────────────────────────────────────────────────
def serialize_order(order) -> dict:
    return {
        "id": str(order["_id"]),
        "user_id": order["user_id"],
        "product_id": order["product_id"],
        "quantity": order["quantity"],
        "status": order["status"],
    }


# ─── Routes ─────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "service": "order-service",
        "status": "running",
        "message": "Order Service is operational"
    }


@app.get("/health")
async def health():
    return {"service": "order-service", "status": "healthy"}


# Create Order
@app.post("/orders", response_model=OrderResponse)
async def create_order(order: OrderCreate):
    order_data = order.dict()
    order_data["status"] = "CREATED"

    result = orders_collection.insert_one(order_data)
    new_order = orders_collection.find_one({"_id": result.inserted_id})

    return serialize_order(new_order)


# Get All Orders
@app.get("/orders", response_model=List[OrderResponse])
async def get_orders():
    orders = orders_collection.find()
    return [serialize_order(order) for order in orders]


# Get Order by ID
@app.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str):
    try:
        order = orders_collection.find_one({"_id": ObjectId(order_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid Order ID")

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return serialize_order(order)


# Update Order Status
@app.put("/orders/{order_id}/status")
async def update_order_status(order_id: str, status: str):
    try:
        result = orders_collection.update_one(
            {"_id": ObjectId(order_id)},
            {"$set": {"status": status}}
        )
    except:
        raise HTTPException(status_code=400, detail="Invalid Order ID")

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")

    return {"message": "Order status updated successfully"}


# Delete Order
@app.delete("/orders/{order_id}")
async def delete_order(order_id: str):
    try:
        result = orders_collection.delete_one({"_id": ObjectId(order_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid Order ID")

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")

    return {"message": "Order deleted successfully"}