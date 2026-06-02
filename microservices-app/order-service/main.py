from fastapi import FastAPI, HTTPException, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from typing import Optional, List
from bson import ObjectId
from bson.errors import InvalidId
import motor.motor_asyncio
import os

<<<<<<< HEAD
from site_favicon import site_favicon_link_tag

app = FastAPI(
    title="Order Service",
    description="Order Processing Microservice — E-Commerce Platform",
    version="1.0.0",
)
=======
app = FastAPI(title="Order Service", description="Order Processing Microservice", version="1.0.0")
>>>>>>> service-mesh

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb-service.ecommerce.svc.cluster.local:27017")
DB_NAME = os.getenv("DB_NAME", "orderdb")

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]
collection = db["orders"]

class OrderCreate(BaseModel):
    customer: str = Field(..., min_length=2)
    product: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1)
    status: str = "Pending"

class OrderUpdate(BaseModel):
    customer: Optional[str] = None
    product: Optional[str] = None
    quantity: Optional[int] = None
    status: Optional[str] = None

class OrderOut(BaseModel):
    id: str
    customer: str
    product: str
    quantity: int
    status: str

def valid_object_id(oid: str) -> ObjectId:
    try:
        return ObjectId(oid)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order ID")

def order_doc_to_out(doc):
    return {
        "id": str(doc["_id"]),
        "customer": doc.get("customer", ""),
        "product": doc.get("product", ""),
        "quantity": doc.get("quantity", 0),
        "status": doc.get("status", "Pending"),
    }

HTML_STYLE = """
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Arial,sans-serif;background:#f7f3e8;color:#1f3b24}
header{background:linear-gradient(135deg,#315c35,#1f7a3a);padding:20px 45px;color:white;display:flex;gap:15px;align-items:center}
.logo{font-size:2rem} header span{color:#d8f3dc}
.container{max-width:1200px;margin:auto;padding:35px 20px}
.stats-bar{display:flex;gap:18px;margin-bottom:30px;flex-wrap:wrap}
.stat-card,.panel{background:white;border:1px solid #c7dcc7;border-radius:16px;padding:25px;margin-bottom:25px;box-shadow:0 2px 8px rgba(49,92,53,.12)}
.stat-card{flex:1;text-align:center}.num{font-size:2rem;font-weight:bold;color:#1f7a3a}.lbl{color:#315c35;font-weight:600}
.panel h2{color:#1f7a3a;margin-bottom:18px}
.create-form{display:grid;grid-template-columns:1fr 1fr;gap:16px}.full{grid-column:1/-1}
label{color:#315c35;font-weight:bold;display:block;margin-bottom:6px}
input,select{width:100%;padding:12px;border:1px solid #9abc9a;border-radius:8px;background:#fbfaf3}
.btn{background:linear-gradient(135deg,#315c35,#1f7a3a);color:white;border:none;padding:11px 22px;border-radius:8px;font-weight:bold;cursor:pointer}
.btn-danger{background:#b91c1c}.btn-sm{padding:6px 12px}
table{width:100%;border-collapse:collapse}th{background:#e4efdf;color:#315c35;padding:12px;text-align:left}td{padding:12px;border-bottom:1px solid #e6e1cf}
tr:hover td{background:#f1f6ee}.empty-state{text-align:center;padding:35px;color:#7a997a}
</style>
"""

def render_page(content):
    return f"""
    <html>
<<<<<<< HEAD
    <head>
    <title>Order Dashboard</title>
    {site_favicon_link_tag()}
    {HTML_STYLE}
    </head>

=======
    <head><title>Order Service</title>{HTML_STYLE}</head>
>>>>>>> service-mesh
    <body>
      <header><div class="logo">🛍️</div><div><h1>Order Service</h1><span>Order Processing Microservice</span></div></header>
      <div class="container">{content}</div>
    </body>
    </html>
    """

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    orders = await collection.find().to_list(1000)
    total = len(orders)
    pending = sum(1 for o in orders if o.get("status") == "Pending")
    delivered = sum(1 for o in orders if o.get("status") == "Delivered")
    cancelled = sum(1 for o in orders if o.get("status") == "Cancelled")

    rows = ""
    for o in orders:
        oid = str(o["_id"])
        rows += f"""
        <tr>
          <td>{oid}</td><td>{o.get('customer','')}</td><td>{o.get('product','')}</td>
          <td>{o.get('quantity',0)}</td><td>{o.get('status','Pending')}</td>
          <td>
            <form action="/delete/{oid}" method="post" style="display:inline">
              <button class="btn btn-danger btn-sm">Delete</button>
            </form>
          </td>
        </tr>
        """

    content = f"""
    <div class="stats-bar">
      <div class="stat-card"><div class="num">{total}</div><div class="lbl">Total Orders</div></div>
      <div class="stat-card"><div class="num">{pending}</div><div class="lbl">Pending</div></div>
      <div class="stat-card"><div class="num">{delivered}</div><div class="lbl">Delivered</div></div>
      <div class="stat-card"><div class="num">{cancelled}</div><div class="lbl">Cancelled</div></div>
    </div>

    <div class="panel">
      <h2>➕ Place New Order</h2>
      <form class="create-form" action="/create" method="post">
        <div><label>Customer Name</label><input name="customer" required></div>
        <div><label>Product Name</label><input name="product" required></div>
        <div><label>Quantity</label><input name="quantity" type="number" value="1" required></div>
        <div><label>Status</label><select name="status"><option>Pending</option><option>Delivered</option><option>Cancelled</option></select></div>
        <div class="full"><button class="btn">Create Order</button></div>
      </form>
    </div>

    <div class="panel">
      <h2>📋 Order History</h2>
      <table>
        <tr><th>ID</th><th>Customer</th><th>Product</th><th>Quantity</th><th>Status</th><th>Action</th></tr>
        {rows if rows else '<tr><td colspan="6" class="empty-state">No orders yet</td></tr>'}
      </table>
    </div>
    """
    return render_page(content)

@app.post("/create")
async def create_order(customer: str = Form(...), product: str = Form(...), quantity: int = Form(...), status: str = Form(...)):
    await collection.insert_one({"customer": customer, "product": product, "quantity": quantity, "status": status})
    return RedirectResponse("/", status_code=303)

@app.post("/delete/{order_id}")
async def delete_order(order_id: str):
    await collection.delete_one({"_id": valid_object_id(order_id)})
    return RedirectResponse("/", status_code=303)

@app.post("/orders/", response_model=OrderOut)
async def api_create_order(order: OrderCreate):
    doc = jsonable_encoder(order)
    result = await collection.insert_one(doc)
    created = await collection.find_one({"_id": result.inserted_id})
    return order_doc_to_out(created)

@app.get("/orders/", response_model=List[OrderOut])
async def api_list_orders():
    docs = await collection.find().to_list(1000)
    return [order_doc_to_out(d) for d in docs]

@app.get("/health")
async def health():
    return {"service": "order-service", "status": "healthy", "db": DB_NAME}