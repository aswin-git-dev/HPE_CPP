from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from datetime import datetime
from pymongo import MongoClient
import uuid
import os

# ---------------------------
# MongoDB setup
# ---------------------------
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
client = MongoClient(MONGO_URI)
db = client.notification_db
collection = db.notifications

# ---------------------------
# FastAPI app
# ---------------------------
app = FastAPI(title="Notification Service", version="0.1.0")

# ---------------------------
# Request models
# ---------------------------
class EmailRequest(BaseModel):
    user_id: str
    email: EmailStr
    subject: str
    message: str

class SMSRequest(BaseModel):
    user_id: str
    phone: str
    message: str

# ---------------------------
# Root endpoint
# ---------------------------
@app.get("/")
def service_info():
    return {"service": "notification-service", "status": "running"}

# ---------------------------
# Health check
# ---------------------------
@app.get("/health")
def health_check():
    return {"status": "healthy"}

# ---------------------------
# Send Email (mock)
# ---------------------------
@app.post("/notifications/email")
def send_email(email_req: EmailRequest):
    notification_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    
    # Save to MongoDB
    doc = {
        "notification_id": notification_id,
        "type": "email",
        "user_id": email_req.user_id,
        "email": email_req.email,
        "subject": email_req.subject,
        "message": email_req.message,
        "timestamp": timestamp
    }
    collection.insert_one(doc)
    
    return JSONResponse(content={
        "status": "Email sent successfully (mock)",
        "notification_id": notification_id,
        "timestamp": timestamp
    })

# ---------------------------
# Send SMS (mock)
# ---------------------------
@app.post("/notifications/sms")
def send_sms(sms_req: SMSRequest):
    notification_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    
    # Save to MongoDB
    doc = {
        "notification_id": notification_id,
        "type": "sms",
        "user_id": sms_req.user_id,
        "phone": sms_req.phone,
        "message": sms_req.message,
        "timestamp": timestamp
    }
    collection.insert_one(doc)
    
    return JSONResponse(content={
        "status": "SMS sent successfully (mock)",
        "notification_id": notification_id,
        "timestamp": timestamp
    })

# ---------------------------
# Notification History
# ---------------------------
@app.get("/notifications/{user_id}/history")
def get_history(user_id: str):
    records = list(collection.find({"user_id": user_id}, {"_id": 0}))
    if not records:
        return JSONResponse(content={"message": f"No notifications found for user {user_id}"})
    return records