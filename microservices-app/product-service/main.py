"""Product Service - FastAPI Microservice"""
from fastapi import FastAPI, HTTPException, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from typing import Optional, List
from bson import ObjectId
from bson.errors import InvalidId
import motor.motor_asyncio
import os


# App Setup
app = FastAPI(
    title="Product Service",
    description="Product Catalog Microservice — E-Commerce Platform",
    version="1.0.0",
)

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME   = os.getenv("DB_NAME", "productdb")

client     = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
db         = client[DB_NAME]
collection = db["products"]


# Pydantic Models
class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    price: float = Field(..., gt=0)
    quantity: int = Field(default=0, ge=0)
    category: Optional[str] = None

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    category: Optional[str] = None

class ProductOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    price: float
    quantity: int
    category: Optional[str]


# Helpers
def product_doc_to_out(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name", ""),
        "description": doc.get("description", ""),
        "price": doc.get("price", 0.0),
        "quantity": doc.get("quantity", 0),
        "category": doc.get("category", ""),
    }

def valid_object_id(oid: str) -> ObjectId:
    try:
        return ObjectId(oid)
    except (InvalidId, Exception):
        raise HTTPException(status_code=400, detail=f"Invalid product ID: {oid}")


# HTML Frontend
HTML_STYLE = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Inter', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    background: #f7f3e8;
    min-height: 100vh;
    color: #1f3b24;
  }

  header {
    background: linear-gradient(135deg, #315c35, #1f7a3a);
    border-bottom: 1px solid #244628;
    padding: 18px 40px;
    display: flex;
    align-items: center;
    gap: 16px;
    box-shadow: 0 2px 12px rgba(49,92,53,0.25);
  }

  header .logo { font-size: 2rem; }
  header h1 { font-size: 1.6rem; font-weight: 700; color: #ffffff; }
  header span { font-size: 0.85rem; color: #d8f3dc; }

  .container { max-width: 1200px; margin: 0 auto; padding: 32px 20px; }

  .stats-bar {
    display: flex;
    gap: 16px;
    margin-bottom: 32px;
    flex-wrap: wrap;
  }

  .stat-card {
    background: #ffffff;
    border: 1px solid #c7dcc7;
    border-radius: 12px;
    padding: 18px 28px;
    flex: 1;
    min-width: 160px;
    text-align: center;
    box-shadow: 0 2px 8px rgba(49,92,53,0.08);
  }

  .stat-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 18px rgba(49,92,53,0.14);
  }

  .stat-card .num {
    font-size: 2rem;
    font-weight: 800;
    color: #1f7a3a;
  }

  .stat-card .lbl {
    font-size: 0.8rem;
    color: #315c35;
    margin-top: 4px;
    font-weight: 500;
  }

  .panel {
    background: #ffffff;
    border: 1px solid #c7dcc7;
    border-radius: 16px;
    padding: 28px;
    margin-bottom: 28px;
    box-shadow: 0 2px 10px rgba(49,92,53,0.07);
  }

  .panel h2 {
    font-size: 1.1rem;
    color: #1f7a3a;
    margin-bottom: 20px;
    font-weight: 700;
  }

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
    border: 1px solid #9abc9a;
    background: #fbfaf3;
    color: #1f3b24;
    font-size: 0.9rem;
    outline: none;
  }

  input:focus, select:focus {
    border-color: #1f7a3a;
    box-shadow: 0 0 0 3px rgba(31,122,58,0.15);
  }

  input::placeholder { color: #9abc9a; }

  label {
    font-size: 0.8rem;
    color: #315c35;
    display: block;
    margin-bottom: 4px;
    font-weight: 600;
  }

  .btn {
    padding: 10px 22px;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    font-size: 0.9rem;
    font-weight: 600;
  }

  .btn-primary {
    background: linear-gradient(135deg, #315c35, #1f7a3a);
    color: #ffffff;
    box-shadow: 0 2px 8px rgba(49,92,53,0.3);
  }

  .btn-primary:hover {
    opacity: 0.9;
    transform: translateY(-1px);
    box-shadow: 0 4px 14px rgba(49,92,53,0.4);
  }

  .btn-danger { background: #b91c1c; color: #fff; }
  .btn-danger:hover { opacity: 0.85; }
  .btn-sm { padding: 6px 14px; font-size: 0.8rem; }

  table {
    width: 100%;
    border-collapse: collapse;
  }

  th {
    background: #e4efdf;
    padding: 12px 16px;
    text-align: left;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #315c35;
    font-weight: 700;
  }

  td {
    padding: 12px 16px;
    border-bottom: 1px solid #e6e1cf;
    font-size: 0.88rem;
    color: #1f3b24;
  }

  tr:hover td { background: #f1f6ee; }

  .badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 600;
  }

  .empty-state {
    text-align: center;
    padding: 40px;
    color: #7a997a;
  }

  .alert {
    padding: 12px 20px;
    border-radius: 8px;
    margin-bottom: 20px;
    font-size: 0.9rem;
  }

  .alert-success {
    background: #dcfce7;
    border: 1px solid #16a34a;
    color: #15803d;
  }

  .alert-error {
    background: #fee2e2;
    border: 1px solid #dc2626;
    color: #b91c1c;
  }

  .services-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px,1fr));
    gap: 14px;
  }

  .svc-card {
    background: #fbfaf3;
    border: 1px solid #c7dcc7;
    border-radius: 12px;
    padding: 18px;
    text-align: center;
  }

  .svc-card:hover {
    box-shadow: 0 4px 14px rgba(49,92,53,0.12);
  }

  .svc-card .icon {
    font-size: 2rem;
    margin-bottom: 8px;
  }

  .svc-card .name {
    font-size: 0.9rem;
    font-weight: 600;
    color: #315c35;
  }

  .svc-card .status {
    font-size: 0.75rem;
    color: #1f7a3a;
    margin-top: 4px;
  }

  .svc-card .dot {
    display:inline-block;
    width:8px;
    height:8px;
    border-radius:50%;
    margin-right:5px;
  }

  .dot-active { background:#16a34a; }
  .dot-stub { background:#f59e0b; }
</style>
"""                                                                                                                           


def render_page(content: str, alert: str = "", alert_type: str = "success") -> str:
    banner = f"<div class='alert alert-{alert_type}'>{alert}</div>" if alert else ""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Product Service Dashboard</title>
  {HTML_STYLE}
</head>
<body>
  <header>
    <div class="logo">📦</div>
    <div>
      <h1>Product Service</h1>
      <span>Catalog Management</span>
    </div>
  </header>
  <div class="container">
    {banner}
    {content}
  </div>
</body>
</html>
"""

# Frontend Routes
@app.get("/", response_class=HTMLResponse, tags=["Frontend"])
async def dashboard(request: Request, msg: str = "", err: str = ""):
    products = await collection.find().to_list(1000)
    total = len(products)

    rows = ""
    for p in products:
        cid = p.get('category','') or '—'
        uid = str(p["_id"])
        rows += f"""
        <tr>
          <td>{p.get('name','')}</td>
          <td>{p.get('price',0):.2f}</td>
          <td>{p.get('quantity',0)}</td>
          <td>{cid}</td>
          <td>
            <a href="/edit/{uid}"><button class="btn btn-primary btn-sm">✏ Edit</button></a>
            &nbsp;
            <form action="/delete/{uid}" method="post" style="display:inline"
                  onsubmit="return confirm('Delete this product?')">
              <button class="btn btn-danger btn-sm">🗑 Delete</button>
            </form>
          </td>
        </tr>"""

    table = f"""
    <table>
      <thead><tr>
        <th>Name</th><th>Price</th><th>Qty</th><th>Category</th><th>Actions</th>
      </tr></thead>
      <tbody>{rows if rows else '<tr><td colspan="5" class="empty-state">No products found. Add one above!</td></tr>'}</tbody>
    </table>""" if total else '<div class="empty-state">🎉 No products yet — create the first one above!</div>'

    content = f"""
    <div class="stats-bar">
      <div class="stat-card"><div class="num">{total}</div><div class="lbl">Total Products</div></div>
    </div>

    <div class="panel">
      <h2>➕ Add New Product</h2>
      <form class="create-form" action="/create" method="post">
        <div>
          <label>Product Name *</label>
          <input name="name" placeholder="e.g. Wireless Mouse" required>
        </div>
        <div>
          <label>Price *</label>
          <input name="price" type="number" step="0.01" placeholder="e.g. 19.99" required>
        </div>
        <div>
          <label>Quantity</label>
          <input name="quantity" type="number" value="0">
        </div>
        <div>
          <label>Category</label>
          <input name="category" placeholder="e.g. Electronics">
        </div>
        <div class="full">
          <label>Description</label>
          <input name="description" placeholder="Short description">
        </div>
        <div class="full">
          <button class="btn btn-primary" type="submit">Create Product</button>
        </div>
      </form>
    </div>

    <div class="panel">
      <h2>Catalog</h2>
      {table}
    </div>

    

    <div class="panel">
      <h2>📡 API Reference</h2>
      <p style="color:#2563eb;font-size:0.88rem;margin-bottom:12px">
        Full REST API available — <a href="/docs" style="color:#1d4ed8;font-weight:600">Interactive Docs (Swagger)</a> &nbsp;|&nbsp;
        <a href="/redoc" style="color:#1d4ed8;font-weight:600">ReDoc</a>
      </p>
      <table>
        <thead><tr><th>Method</th><th>Endpoint</th><th>Description</th></tr></thead>
        <tbody>
          <tr><td>GET</td><td>/products/</td><td>List all products</td></tr>
          <tr><td>POST</td><td>/products/</td><td>Create product (JSON)</td></tr>
          <tr><td>GET</td><td>/products/{{id}}</td><td>Get product by ID</td></tr>
          <tr><td>PUT</td><td>/products/{{id}}</td><td>Update product (JSON)</td></tr>
          <tr><td>DELETE</td><td>/products/{{id}}</td><td>Delete product</td></tr>
          <tr><td>GET</td><td>/health</td><td>Health check</td></tr>
        </tbody>
      </table>
    </div>
    """
    alert_msg  = msg or err
    alert_type = "error" if err else "success"
    return render_page(content, alert_msg, alert_type)


@app.get("/edit/{product_id}", response_class=HTMLResponse, tags=["Frontend"])
async def edit_page(product_id: str):
    doc = await collection.find_one({"_id": valid_object_id(product_id)})
    if not doc:
        return RedirectResponse("/?err=Product+not+found", status_code=303)
    p = product_doc_to_out(doc)
    content = f"""
    <div class="panel" style="max-width:600px;margin:0 auto">
      <h2>✏️ Edit Product</h2>
      <form class="create-form" action="/update/{p['id']}" method="post">
        <div>
          <label>Product Name</label>
          <input name="name" value="{p['name']}" required>
        </div>
        <div>
          <label>Price</label>
          <input name="price" type="number" step="0.01" value="{p['price']:.2f}" required>
        </div>
        <div>
          <label>Quantity</label>
          <input name="quantity" type="number" value="{p['quantity']}">
        </div>
        <div>
          <label>Category</label>
          <input name="category" value="{p['category'] or ''}">
        </div>
        <div class="full">
          <label>Description</label>
          <input name="description" value="{p['description'] or ''}">
        </div>
        <div class="full">
          <button class="btn btn-primary" type="submit"> Update Product</button>
        </div>
      </form>
    </div>
    """
    return render_page(content)


@app.post("/create", response_class=RedirectResponse, tags=["Frontend"])
async def create_product(
    name: str = Form(...),
    price: float = Form(...),
    quantity: int = Form(0),
    category: str = Form(""),
    description: str = Form(""),
):
    doc = {"name": name, "price": price, "quantity": quantity, "category": category, "description": description}
    await collection.insert_one(doc)
    return RedirectResponse("/?msg=Product+created", status_code=303)


@app.post("/update/{product_id}", response_class=RedirectResponse, tags=["Frontend"])
async def update_product(
    product_id: str,
    name: str = Form(...),
    price: float = Form(...),
    quantity: int = Form(0),
    category: str = Form(""),
    description: str = Form(""),
):
    oid = valid_object_id(product_id)
    update_data = {"name": name, "price": price, "quantity": quantity, "category": category, "description": description}
    await collection.update_one({"_id": oid}, {"$set": update_data})
    return RedirectResponse("/?msg=Product+updated", status_code=303)


@app.post("/delete/{product_id}", response_class=RedirectResponse, tags=["Frontend"])
async def delete_product(product_id: str):
    await collection.delete_one({"_id": valid_object_id(product_id)})
    return RedirectResponse("/?msg=Product+deleted", status_code=303)


# JSON API Routes

@app.post("/products/", response_model=ProductOut, status_code=201, tags=["Products API"])
async def create_api(p: ProductCreate):
    doc = jsonable_encoder(p)
    result = await collection.insert_one(doc)
    doc["_id"] = result.inserted_id
    return product_doc_to_out(doc)


@app.get("/products/", response_model=List[ProductOut], tags=["Products API"])
async def list_api():
    docs = await collection.find().to_list(1000)
    return [product_doc_to_out(d) for d in docs]


@app.get("/products/{product_id}", response_model=ProductOut, tags=["Products API"])
async def get_api(product_id: str):
    doc = await collection.find_one({"_id": valid_object_id(product_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    return product_doc_to_out(doc)


@app.put("/products/{product_id}", response_model=ProductOut, tags=["Products API"])
async def update_api(product_id: str, p: ProductUpdate):
    oid = valid_object_id(product_id)
    update_data = {k: v for k, v in p.dict().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided for update")
    await collection.update_one({"_id": oid}, {"$set": update_data})
    doc = await collection.find_one({"_id": oid})
    return product_doc_to_out(doc)


@app.delete("/products/{product_id}", status_code=200, tags=["Products API"])
async def delete_api(product_id: str):
    oid = valid_object_id(product_id)
    result = await collection.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"status": "deleted"}


@app.get("/health")
async def health():
    return {"service": "product-service", "status": "ok"}
