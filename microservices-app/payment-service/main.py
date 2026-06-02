from fastapi import FastAPI, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from typing import Optional, List
from bson import ObjectId
from bson.errors import InvalidId
import motor.motor_asyncio
import os

app = FastAPI(title="Payment Service", description="Payment Processing Microservice", version="1.0.0")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb-service.ecommerce.svc.cluster.local:27017")
DB_NAME = os.getenv("DB_NAME", "paymentdb")

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]
collection = db["payments"]

class PaymentCreate(BaseModel):
    customer: str = Field(..., min_length=2)
    amount: float = Field(..., gt=0)
    method: str
    status: str = "Success"

class PaymentOut(BaseModel):
    id: str
    customer: str
    amount: float
    method: str
    status: str

def valid_object_id(oid: str) -> ObjectId:
    try:
        return ObjectId(oid)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payment ID")

def payment_doc_to_out(doc):
    return {
        "id": str(doc["_id"]),
        "customer": doc.get("customer", ""),
        "amount": doc.get("amount", 0.0),
        "method": doc.get("method", ""),
        "status": doc.get("status", "Success"),
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
    <head><title>Payment Service</title>{HTML_STYLE}</head>
    <body>
      <header><div class="logo">💳</div><div><h1>Payment Service</h1><span>Payment Gateway and Transaction Processing</span></div></header>
      <div class="container">{content}</div>
    </body>
    </html>
    """

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    payments = await collection.find().to_list(1000)
    total = len(payments)
    success = sum(1 for p in payments if p.get("status") == "Success")
    pending = sum(1 for p in payments if p.get("status") == "Pending")
    failed = sum(1 for p in payments if p.get("status") == "Failed")

    rows = ""
    for p in payments:
        pid = str(p["_id"])
        rows += f"""
        <tr>
          <td>{pid}</td><td>{p.get('customer','')}</td><td>₹{p.get('amount',0)}</td>
          <td>{p.get('method','')}</td><td>{p.get('status','')}</td>
          <td>
            <form action="/delete/{pid}" method="post" style="display:inline">
              <button class="btn btn-danger btn-sm">Delete</button>
            </form>
          </td>
        </tr>
        """

    content = f"""
    <div class="stats-bar">
      <div class="stat-card"><div class="num">{total}</div><div class="lbl">Total Payments</div></div>
      <div class="stat-card"><div class="num">{success}</div><div class="lbl">Success</div></div>
      <div class="stat-card"><div class="num">{pending}</div><div class="lbl">Pending</div></div>
      <div class="stat-card"><div class="num">{failed}</div><div class="lbl">Failed</div></div>
    </div>

    <div class="panel">
      <h2>➕ Process Payment</h2>
      <form class="create-form" action="/create" method="post">
        <div><label>Customer Name</label><input name="customer" required></div>
        <div><label>Amount</label><input name="amount" type="number" step="0.01" required></div>
        <div><label>Method</label><select name="method"><option>UPI</option><option>Card</option><option>Net Banking</option><option>Wallet</option><option>Cash on Delivery</option></select></div>
        <div><label>Status</label><select name="status"><option>Success</option><option>Pending</option><option>Failed</option></select></div>
        <div class="full"><button class="btn">Process Payment</button></div>
      </form>
    </div>

    <div class="panel">
      <h2>📋 Payment History</h2>
      <table>
        <tr><th>ID</th><th>Customer</th><th>Amount</th><th>Method</th><th>Status</th><th>Action</th></tr>
        {rows if rows else '<tr><td colspan="6" class="empty-state">No payments yet</td></tr>'}
      </table>
    </div>
    """
    return render_page(content)

@app.post("/create")
async def create_payment(customer: str = Form(...), amount: float = Form(...), method: str = Form(...), status: str = Form(...)):
    await collection.insert_one({"customer": customer, "amount": amount, "method": method, "status": status})
    return RedirectResponse("/", status_code=303)

@app.post("/delete/{payment_id}")
async def delete_payment(payment_id: str):
    await collection.delete_one({"_id": valid_object_id(payment_id)})
    return RedirectResponse("/", status_code=303)

@app.post("/payments/", response_model=PaymentOut)
async def api_create_payment(payment: PaymentCreate):
    doc = jsonable_encoder(payment)
    result = await collection.insert_one(doc)
    created = await collection.find_one({"_id": result.inserted_id})
    return payment_doc_to_out(created)

@app.get("/payments/", response_model=List[PaymentOut])
async def api_list_payments():
    docs = await collection.find().to_list(1000)
    return [payment_doc_to_out(d) for d in docs]

@app.get("/health")
async def health():
    return {"service": "payment-service", "status": "healthy", "db": DB_NAME}