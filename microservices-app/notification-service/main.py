from fastapi import FastAPI, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from typing import List
from bson import ObjectId
import motor.motor_asyncio
import os

app = FastAPI(title="Notification Service", description="Notification Microservice", version="1.0.0")

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb-service.ecommerce.svc.cluster.local:27017")
DB_NAME = os.getenv("DB_NAME", "notificationdb")

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]
collection = db["notifications"]

class NotificationCreate(BaseModel):
    user: str = Field(..., min_length=2)
    type: str
    message: str
    status: str = "Sent"

class NotificationOut(BaseModel):
    id: str
    user: str
    type: str
    message: str
    status: str

def valid_object_id(oid: str) -> ObjectId:
    try:
        return ObjectId(oid)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid notification ID")

def notification_doc_to_out(doc):
    return {
        "id": str(doc["_id"]),
        "user": doc.get("user", ""),
        "type": doc.get("type", ""),
        "message": doc.get("message", ""),
        "status": doc.get("status", "Sent"),
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
    <head><title>Notification Service</title>{HTML_STYLE}</head>
    <body>
      <header><div class="logo">🔔</div><div><h1>Notification Service</h1><span>Email, SMS and App Notification Microservice</span></div></header>
      <div class="container">{content}</div>
    </body>
    </html>
    """

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    notifications = await collection.find().to_list(1000)
    total = len(notifications)
    sent = sum(1 for n in notifications if n.get("status") == "Sent")
    pending = sum(1 for n in notifications if n.get("status") == "Pending")
    failed = sum(1 for n in notifications if n.get("status") == "Failed")

    rows = ""
    for n in notifications:
        nid = str(n["_id"])
        rows += f"""
        <tr>
          <td>{nid}</td><td>{n.get('user','')}</td><td>{n.get('type','')}</td>
          <td>{n.get('message','')}</td><td>{n.get('status','')}</td>
          <td>
            <form action="/delete/{nid}" method="post" style="display:inline">
              <button class="btn btn-danger btn-sm">Delete</button>
            </form>
          </td>
        </tr>
        """

    content = f"""
    <div class="stats-bar">
      <div class="stat-card"><div class="num">{total}</div><div class="lbl">Total Notifications</div></div>
      <div class="stat-card"><div class="num">{sent}</div><div class="lbl">Sent</div></div>
      <div class="stat-card"><div class="num">{pending}</div><div class="lbl">Pending</div></div>
      <div class="stat-card"><div class="num">{failed}</div><div class="lbl">Failed</div></div>
    </div>

    <div class="panel">
      <h2>➕ Send Notification</h2>
      <form class="create-form" action="/create" method="post">
        <div><label>User Name</label><input name="user" required></div>
        <div><label>Type</label><select name="type"><option>Email</option><option>SMS</option><option>App Notification</option></select></div>
        <div class="full"><label>Message</label><input name="message" required></div>
        <div><label>Status</label><select name="status"><option>Sent</option><option>Pending</option><option>Failed</option></select></div>
        <div class="full"><button class="btn">Send Notification</button></div>
      </form>
    </div>

    <div class="panel">
      <h2>📋 Notification History</h2>
      <table>
        <tr><th>ID</th><th>User</th><th>Type</th><th>Message</th><th>Status</th><th>Action</th></tr>
        {rows if rows else '<tr><td colspan="6" class="empty-state">No notifications yet</td></tr>'}
      </table>
    </div>
    """
    return render_page(content)

@app.post("/create")
async def create_notification(user: str = Form(...), type: str = Form(...), message: str = Form(...), status: str = Form(...)):
    await collection.insert_one({"user": user, "type": type, "message": message, "status": status})
    return RedirectResponse("/", status_code=303)

@app.post("/delete/{notification_id}")
async def delete_notification(notification_id: str):
    await collection.delete_one({"_id": valid_object_id(notification_id)})
    return RedirectResponse("/", status_code=303)

@app.post("/notifications/", response_model=NotificationOut)
async def api_create_notification(notification: NotificationCreate):
    doc = jsonable_encoder(notification)
    result = await collection.insert_one(doc)
    created = await collection.find_one({"_id": result.inserted_id})
    return notification_doc_to_out(created)

@app.get("/notifications/", response_model=List[NotificationOut])
async def api_list_notifications():
    docs = await collection.find().to_list(1000)
    return [notification_doc_to_out(d) for d in docs]

@app.get("/health")
async def health():
    return {"service": "notification-service", "status": "healthy", "db": DB_NAME}