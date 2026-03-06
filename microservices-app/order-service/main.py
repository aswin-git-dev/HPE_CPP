from fastapi import FastAPI, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
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


# ─── Models ────────────────────────────────────────────────────────────────
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


# ─── Utility Function ──────────────────────────────────────────────────────
def serialize_order(order):
    return {
        "id": str(order["_id"]),
        "user_id": order["user_id"],
        "product_id": order["product_id"],
        "quantity": order["quantity"],
        "status": order["status"],
    }


# ─── Simple UI Style ───────────────────────────────────────────────────────
HTML_STYLE = """
<style>
body{
font-family: Arial;
background:#f4f6fb;
padding:30px;
}
h1{
color:#1d4ed8;
}
table{
border-collapse:collapse;
width:100%;
margin-top:20px;
}
th,td{
border:1px solid #ddd;
padding:10px;
text-align:center;
}
th{
background:#1d4ed8;
color:white;
}
form{
margin-bottom:20px;
}
input{
padding:8px;
margin-right:10px;
}
button{
padding:8px 14px;
background:#1d4ed8;
color:white;
border:none;
cursor:pointer;
}
</style>
"""


# ─── UI Dashboard ──────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard():

    orders = list(orders_collection.find())

    rows = ""

    for order in orders:
        rows += f"""
        <tr>
        <td>{order['user_id']}</td>
        <td>{order['product_id']}</td>
        <td>{order['quantity']}</td>
        <td>{order['status']}</td>
        <td>
        <form action="/delete/{order['_id']}" method="post">
        <button>Delete</button>
        </form>
        </td>
        </tr>
        """

    html = f"""
    <html>
    <head>
    <title>Order Dashboard</title>
    {HTML_STYLE}
    </head>

    <body>

    <h1>📦 Order Service Dashboard</h1>

    <h3>Create Order</h3>

    <form action="/create" method="post">

    <input name="user_id" placeholder="User ID" required>

    <input name="product_id" placeholder="Product ID" required>

    <input name="quantity" type="number" placeholder="Quantity" required>

    <button>Create Order</button>

    </form>

    <h3>All Orders</h3>

    <table>

    <tr>
    <th>User</th>
    <th>Product</th>
    <th>Quantity</th>
    <th>Status</th>
    <th>Action</th>
    </tr>

    {rows}

    </table>

    </body>
    </html>
    """

    return html


# ─── Create Order from UI ─────────────────────────────────────────────────
@app.post("/create")
def create_order_form(
    user_id: str = Form(...),
    product_id: str = Form(...),
    quantity: int = Form(...)
):

    order_data = {
        "user_id": user_id,
        "product_id": product_id,
        "quantity": quantity,
        "status": "CREATED"
    }

    orders_collection.insert_one(order_data)

    return RedirectResponse("/", status_code=303)


# ─── Delete Order from UI ─────────────────────────────────────────────────
@app.post("/delete/{order_id}")
def delete_order_form(order_id: str):

    orders_collection.delete_one({"_id": ObjectId(order_id)})

    return RedirectResponse("/", status_code=303)


# ─── Root API ─────────────────────────────────────────────────────────────
@app.get("/api")
async def root():
    return {
        "service": "order-service",
        "status": "running",
        "message": "Order Service is operational"
    }


# ─── Health Check ─────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"service": "order-service", "status": "healthy"}


# ─── API: Create Order ────────────────────────────────────────────────────
@app.post("/orders", response_model=OrderResponse)
async def create_order(order: OrderCreate):

    order_data = order.dict()
    order_data["status"] = "CREATED"

    result = orders_collection.insert_one(order_data)

    new_order = orders_collection.find_one({"_id": result.inserted_id})

    return serialize_order(new_order)


# ─── API: Get All Orders ──────────────────────────────────────────────────
@app.get("/orders", response_model=List[OrderResponse])
async def get_orders():

    orders = orders_collection.find()

    return [serialize_order(order) for order in orders]


# ─── API: Get Order by ID ─────────────────────────────────────────────────
@app.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str):

    try:
        order = orders_collection.find_one({"_id": ObjectId(order_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid Order ID")

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return serialize_order(order)


# ─── API: Update Order Status ─────────────────────────────────────────────
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


# ─── API: Delete Order ────────────────────────────────────────────────────
@app.delete("/orders/{order_id}")
async def delete_order(order_id: str):

    try:
        result = orders_collection.delete_one({"_id": ObjectId(order_id)})
    except:
        raise HTTPException(status_code=400, detail="Invalid Order ID")

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")

    return {"message": "Order deleted successfully"}