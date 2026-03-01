"""
User Service — FastAPI Microservice
Handles Customer Management for the E-Commerce Platform
MongoDB (Motor async driver) for persistence
"""

from fastapi import FastAPI, HTTPException, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from bson import ObjectId
from bson.errors import InvalidId
import motor.motor_asyncio
import os

# ──────────────────────────────────────────────
# App Setup
# ──────────────────────────────────────────────
app = FastAPI(
    title="User Service",
    description="Customer Management Microservice — E-Commerce Platform",
    version="1.0.0",
)

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME   = os.getenv("DB_NAME", "userdb")

client     = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db         = client[DB_NAME]
collection = db["users"]

# ──────────────────────────────────────────────
# Pydantic Models
# ──────────────────────────────────────────────
class UserCreate(BaseModel):
    name:    str            = Field(..., min_length=2, max_length=100)
    email:   EmailStr
    phone:   str            = Field(..., min_length=10, max_length=15)
    address: Optional[str]  = None
    role:    str            = Field(default="customer")

class UserUpdate(BaseModel):
    name:    Optional[str]  = None
    email:   Optional[EmailStr] = None
    phone:   Optional[str]  = None
    address: Optional[str]  = None
    role:    Optional[str]  = None

class UserOut(BaseModel):
    id:      str
    name:    str
    email:   str
    phone:   str
    address: Optional[str]
    role:    str

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def user_doc_to_out(doc: dict) -> dict:
    return {
        "id":      str(doc["_id"]),
        "name":    doc.get("name", ""),
        "email":   doc.get("email", ""),
        "phone":   doc.get("phone", ""),
        "address": doc.get("address", ""),
        "role":    doc.get("role", "customer"),
    }

def valid_object_id(oid: str) -> ObjectId:
    try:
        return ObjectId(oid)
    except (InvalidId, Exception):
        raise HTTPException(status_code=400, detail=f"Invalid user ID: {oid}")

# ──────────────────────────────────────────────
# HTML Frontend
# ──────────────────────────────────────────────
HTML_STYLE = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Inter', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    background: #f0f4ff;
    min-height: 100vh;
    color: #1e3a5f;
  }
  header {
    background: linear-gradient(135deg, #1d4ed8, #2563eb);
    border-bottom: 1px solid #1e40af;
    padding: 18px 40px;
    display: flex;
    align-items: center;
    gap: 16px;
    box-shadow: 0 2px 12px rgba(29,78,216,0.25);
  }
  header .logo { font-size: 2rem; }
  header h1 { font-size: 1.6rem; font-weight: 700; color: #ffffff; }
  header span { font-size: 0.85rem; color: #bfdbfe; }
  .container { max-width: 1200px; margin: 0 auto; padding: 32px 20px; }
  .stats-bar {
    display: flex; gap: 16px; margin-bottom: 32px; flex-wrap: wrap;
  }
  .stat-card {
    background: #ffffff;
    border: 1px solid #bfdbfe;
    border-radius: 12px;
    padding: 18px 28px;
    flex: 1; min-width: 160px;
    text-align: center;
    box-shadow: 0 2px 8px rgba(29,78,216,0.08);
    transition: transform 0.2s, box-shadow 0.2s;
  }
  .stat-card:hover { transform: translateY(-2px); box-shadow: 0 6px 18px rgba(29,78,216,0.14); }
  .stat-card .num { font-size: 2rem; font-weight: 800; color: #1d4ed8; }
  .stat-card .lbl { font-size: 0.8rem; color: #3b82f6; margin-top: 4px; font-weight: 500; }
  .panel {
    background: #ffffff;
    border: 1px solid #bfdbfe;
    border-radius: 16px;
    padding: 28px;
    margin-bottom: 28px;
    box-shadow: 0 2px 10px rgba(29,78,216,0.07);
  }
  .panel h2 { font-size: 1.1rem; color: #1d4ed8; margin-bottom: 20px; font-weight: 700; }
  form.create-form {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
  }
  form.create-form .full { grid-column: 1 / -1; }
  input, select {
    width: 100%;
    padding: 10px 14px;
    border-radius: 8px;
    border: 1px solid #93c5fd;
    background: #f8faff;
    color: #1e3a5f;
    font-size: 0.9rem;
    outline: none;
    transition: border 0.2s, box-shadow 0.2s;
  }
  input:focus, select:focus {
    border-color: #2563eb;
    box-shadow: 0 0 0 3px rgba(37,99,235,0.15);
  }
  input::placeholder { color: #93c5fd; }
  label { font-size: 0.8rem; color: #2563eb; display: block; margin-bottom: 4px; font-weight: 600; }
  .btn {
    padding: 10px 22px;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    font-size: 0.9rem;
    font-weight: 600;
    transition: all 0.2s;
  }
  .btn-primary {
    background: linear-gradient(135deg, #1d4ed8, #3b82f6);
    color: #ffffff;
    box-shadow: 0 2px 8px rgba(29,78,216,0.3);
  }
  .btn-primary:hover { opacity: 0.9; transform: translateY(-1px); box-shadow: 0 4px 14px rgba(29,78,216,0.4); }
  .btn-danger { background: #dc2626; color: #fff; }
  .btn-danger:hover { opacity: 0.85; }
  .btn-sm { padding: 6px 14px; font-size: 0.8rem; }
  table { width: 100%; border-collapse: collapse; }
  th {
    background: #dbeafe;
    padding: 12px 16px;
    text-align: left;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #1d4ed8;
    font-weight: 700;
  }
  td { padding: 12px 16px; border-bottom: 1px solid #e0eaff; font-size: 0.88rem; color: #1e3a5f; }
  tr:hover td { background: #eff6ff; }
  .badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 600;
  }
  .badge-admin    { background: #fee2e2; color: #dc2626; }
  .badge-customer { background: #dbeafe; color: #1d4ed8; }
  .badge-vendor   { background: #fef3c7; color: #b45309; }
  .empty-state { text-align: center; padding: 40px; color: #93c5fd; }
  .alert { padding: 12px 20px; border-radius: 8px; margin-bottom: 20px; font-size: 0.9rem; }
  .alert-success { background: #dcfce7; border: 1px solid #16a34a; color: #15803d; }
  .alert-error   { background: #fee2e2; border: 1px solid #dc2626; color: #b91c1c; }
  .services-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px,1fr)); gap: 14px; }
  .svc-card {
    background: #f8faff;
    border: 1px solid #bfdbfe;
    border-radius: 12px;
    padding: 18px;
    text-align: center;
    transition: box-shadow 0.2s;
  }
  .svc-card:hover { box-shadow: 0 4px 14px rgba(29,78,216,0.12); }
  .svc-card .icon { font-size: 2rem; margin-bottom: 8px; }
  .svc-card .name { font-size: 0.9rem; font-weight: 600; color: #1d4ed8; }
  .svc-card .status { font-size: 0.75rem; color: #3b82f6; margin-top: 4px; }
  .svc-card .dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px; }
  .dot-active { background:#16a34a; } .dot-stub { background:#f59e0b; }
</style>
"""

def render_page(content: str, msg: str = "", msg_type: str = "success") -> str:
    alert = ""
    if msg:
        alert = f'<div class="alert alert-{msg_type}">{msg}</div>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>User Service — E-Commerce Platform</title>
  {HTML_STYLE}
</head>
<body>
  <header>
    <div class="logo">🛒</div>
    <div>
      <h1>E-Commerce Platform</h1>
      <span>User Service — Customer Management Microservice</span>
    </div>
  </header>
  <div class="container">
    {alert}
    {content}
  </div>
</body>
</html>"""


def _services_section():
    return """
<div class="panel">
  <h2>🌐 Microservices Architecture</h2>
  <div class="services-grid">
    <div class="svc-card">
      <div class="icon">👤</div>
      <div class="name">User Service</div>
      <div class="status"><span class="dot dot-active"></span>Active :8000</div>
    </div>
    <div class="svc-card">
      <div class="icon">📦</div>
      <div class="name">Product Service</div>
      <div class="status"><span class="dot dot-stub"></span>Stub :8001</div>
    </div>
    <div class="svc-card">
      <div class="icon">🛍️</div>
      <div class="name">Order Service</div>
      <div class="status"><span class="dot dot-stub"></span>Stub :8002</div>
    </div>
    <div class="svc-card">
      <div class="icon">💳</div>
      <div class="name">Payment Service</div>
      <div class="status"><span class="dot dot-stub"></span>Stub :8003</div>
    </div>
    <div class="svc-card">
      <div class="icon">🔔</div>
      <div class="name">Notification Service</div>
      <div class="status"><span class="dot dot-stub"></span>Stub :8004</div>
    </div>
  </div>
</div>"""

# ──────────────────────────────────────────────
# Frontend Routes
# ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
async def dashboard(request: Request, msg: str = "", err: str = ""):
    users = await collection.find().to_list(1000)
    total      = len(users)
    admins     = sum(1 for u in users if u.get("role") == "admin")
    customers  = sum(1 for u in users if u.get("role") == "customer")
    vendors    = sum(1 for u in users if u.get("role") == "vendor")

    rows = ""
    for u in users:
        role_badge = f'<span class="badge badge-{u.get("role","customer")}">{u.get("role","customer").capitalize()}</span>'
        uid = str(u["_id"])
        rows += f"""
        <tr>
          <td>{u.get('name','')}</td>
          <td>{u.get('email','')}</td>
          <td>{u.get('phone','')}</td>
          <td>{u.get('address','—') or '—'}</td>
          <td>{role_badge}</td>
          <td>
            <a href="/edit/{uid}"><button class="btn btn-primary btn-sm">✏ Edit</button></a>
            &nbsp;
            <form action="/delete/{uid}" method="post" style="display:inline"
                  onsubmit="return confirm('Delete this user?')">
              <button class="btn btn-danger btn-sm">🗑 Delete</button>
            </form>
          </td>
        </tr>"""

    table = f"""
    <table>
      <thead><tr>
        <th>Name</th><th>Email</th><th>Phone</th><th>Address</th><th>Role</th><th>Actions</th>
      </tr></thead>
      <tbody>{''.join([rows]) if rows else '<tr><td colspan="6" class="empty-state">No users found. Add your first customer! 👆</td></tr>'}</tbody>
    </table>""" if total else '<div class="empty-state">🎉 No users yet — create the first one above!</div>'

    content = f"""
    <div class="stats-bar">
      <div class="stat-card"><div class="num">{total}</div><div class="lbl">Total Users</div></div>
      <div class="stat-card"><div class="num">{customers}</div><div class="lbl">Customers</div></div>
      <div class="stat-card"><div class="num">{vendors}</div><div class="lbl">Vendors</div></div>
      <div class="stat-card"><div class="num">{admins}</div><div class="lbl">Admins</div></div>
    </div>

    <div class="panel">
      <h2>➕ Register New Customer</h2>
      <form class="create-form" action="/create" method="post">
        <div>
          <label>Full Name *</label>
          <input name="name" placeholder="e.g. Aswin Kumar" required>
        </div>
        <div>
          <label>Email Address *</label>
          <input name="email" type="email" placeholder="e.g. aswin@email.com" required>
        </div>
        <div>
          <label>Phone Number *</label>
          <input name="phone" placeholder="e.g. 9876543210" required>
        </div>
        <div>
          <label>Role</label>
          <select name="role">
            <option value="customer">Customer</option>
            <option value="vendor">Vendor</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div class="full">
          <label>Address</label>
          <input name="address" placeholder="e.g. 123 Main St, Chennai, TN">
        </div>
        <div class="full">
          <button class="btn btn-primary" type="submit">✅ Create User</button>
        </div>
      </form>
    </div>

    <div class="panel">
      <h2>👥 All Registered Users</h2>
      {table}
    </div>

    {_services_section()}

    <div class="panel">
      <h2>📡 API Reference</h2>
      <p style="color:#2563eb;font-size:0.88rem;margin-bottom:12px">
        Full REST API available — <a href="/docs" style="color:#1d4ed8;font-weight:600">Interactive Docs (Swagger)</a> &nbsp;|&nbsp;
        <a href="/redoc" style="color:#1d4ed8;font-weight:600">ReDoc</a>
      </p>
      <table>
        <thead><tr><th>Method</th><th>Endpoint</th><th>Description</th></tr></thead>
        <tbody>
          <tr><td>GET</td><td>/users/</td><td>List all users</td></tr>
          <tr><td>POST</td><td>/users/</td><td>Create user (JSON)</td></tr>
          <tr><td>GET</td><td>/users/{{id}}</td><td>Get user by ID</td></tr>
          <tr><td>PUT</td><td>/users/{{id}}</td><td>Update user (JSON)</td></tr>
          <tr><td>DELETE</td><td>/users/{{id}}</td><td>Delete user</td></tr>
          <tr><td>GET</td><td>/health</td><td>Health check</td></tr>
        </tbody>
      </table>
    </div>
    """
    alert_msg  = msg or err
    alert_type = "error" if err else "success"
    return render_page(content, alert_msg, alert_type)


@app.get("/edit/{user_id}", response_class=HTMLResponse, tags=["Frontend"])
async def edit_page(user_id: str):
    doc = await collection.find_one({"_id": valid_object_id(user_id)})
    if not doc:
        return RedirectResponse("/?err=User+not+found", status_code=303)
    u = user_doc_to_out(doc)
    content = f"""
    <div class="panel" style="max-width:600px;margin:0 auto">
      <h2>✏️ Edit User</h2>
      <form class="create-form" action="/update/{u['id']}" method="post">
        <div>
          <label>Full Name</label>
          <input name="name" value="{u['name']}" required>
        </div>
        <div>
          <label>Email Address</label>
          <input name="email" type="email" value="{u['email']}" required>
        </div>
        <div>
          <label>Phone Number</label>
          <input name="phone" value="{u['phone']}" required>
        </div>
        <div>
          <label>Role</label>
          <select name="role">
            <option value="customer" {"selected" if u["role"]=="customer" else ""}>Customer</option>
            <option value="vendor"   {"selected" if u["role"]=="vendor"   else ""}>Vendor</option>
            <option value="admin"    {"selected" if u["role"]=="admin"    else ""}>Admin</option>
          </select>
        </div>
        <div class="full">
          <label>Address</label>
          <input name="address" value="{u['address'] or ''}">
        </div>
        <div class="full" style="display:flex;gap:12px">
          <button class="btn btn-primary" type="submit">💾 Save Changes</button>
          <a href="/"><button class="btn" type="button"
             style="background:#dbeafe;color:#1d4ed8;border:1px solid #93c5fd">Cancel</button></a>
        </div>
      </form>
    </div>"""
    return render_page(content)


# ──────────────────────────────────────────────
# HTML Form POST Handlers (redirect after action)
# ──────────────────────────────────────────────
@app.post("/create", response_class=RedirectResponse, tags=["Frontend"])
async def create_user_form(
    name:    str = Form(...),
    email:   str = Form(...),
    phone:   str = Form(...),
    address: str = Form(""),
    role:    str = Form("customer"),
):
    existing = await collection.find_one({"email": email})
    if existing:
        return RedirectResponse(f"/?err=Email+{email}+already+registered", status_code=303)
    doc = {"name": name, "email": email, "phone": phone, "address": address, "role": role}
    await collection.insert_one(doc)
    return RedirectResponse(f"/?msg=User+{name}+created+successfully!", status_code=303)


@app.post("/update/{user_id}", response_class=RedirectResponse, tags=["Frontend"])
async def update_user_form(
    user_id: str,
    name:    str = Form(...),
    email:   str = Form(...),
    phone:   str = Form(...),
    address: str = Form(""),
    role:    str = Form("customer"),
):
    result = await collection.update_one(
        {"_id": valid_object_id(user_id)},
        {"$set": {"name": name, "email": email, "phone": phone, "address": address, "role": role}},
    )
    if result.matched_count == 0:
        return RedirectResponse("/?err=User+not+found", status_code=303)
    return RedirectResponse(f"/?msg=User+updated+successfully!", status_code=303)


@app.post("/delete/{user_id}", response_class=RedirectResponse, tags=["Frontend"])
async def delete_user_form(user_id: str):
    result = await collection.delete_one({"_id": valid_object_id(user_id)})
    if result.deleted_count == 0:
        return RedirectResponse("/?err=User+not+found", status_code=303)
    return RedirectResponse("/?msg=User+deleted+successfully!", status_code=303)


# ──────────────────────────────────────────────
# REST API Endpoints
# ──────────────────────────────────────────────
@app.post("/users/", response_model=UserOut, status_code=201, tags=["Users API"])
async def api_create_user(user: UserCreate):
    existing = await collection.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=409, detail=f"Email {user.email} already registered")
    doc = jsonable_encoder(user)
    result = await collection.insert_one(doc)
    created = await collection.find_one({"_id": result.inserted_id})
    return user_doc_to_out(created)


@app.get("/users/", response_model=List[UserOut], tags=["Users API"])
async def api_list_users(skip: int = 0, limit: int = 100):
    users = await collection.find().skip(skip).limit(limit).to_list(limit)
    return [user_doc_to_out(u) for u in users]


@app.get("/users/{user_id}", response_model=UserOut, tags=["Users API"])
async def api_get_user(user_id: str):
    doc = await collection.find_one({"_id": valid_object_id(user_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    return user_doc_to_out(doc)


@app.put("/users/{user_id}", response_model=UserOut, tags=["Users API"])
async def api_update_user(user_id: str, update: UserUpdate):
    data = {k: v for k, v in update.model_dump().items() if v is not None}
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = await collection.update_one({"_id": valid_object_id(user_id)}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    doc = await collection.find_one({"_id": valid_object_id(user_id)})
    return user_doc_to_out(doc)


@app.delete("/users/{user_id}", status_code=200, tags=["Users API"])
async def api_delete_user(user_id: str):
    result = await collection.delete_one({"_id": valid_object_id(user_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": f"User {user_id} deleted successfully"}


@app.get("/health", tags=["System"])
async def health_check():
    return {"service": "user-service", "status": "healthy", "db": DB_NAME}
