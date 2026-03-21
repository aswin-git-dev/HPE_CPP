# Hybrid Log Analyzer 🔥

This project is a hybrid AI + rule-based system for log classification.

## Features
- ML models: Logistic Regression, Random Forest, XGBoost
- Rule-based detection (admin access, 500 errors, etc.)
- TF-IDF text processing
- Real-time API using FastAPI

## Project Structure
- src/ → training + inference
- tests/ → batch testing
- deploy/ → API
- artifacts/ → saved models

## How to Run

### 1. Install dependencies
pip install -r requirements.txt

### 2. Train model
python src/train_hybrid.py

### 3. Test model
python -m tests.test_hybrid

### 4. Run API
uvicorn deploy.app:app --reload

### 5. Open API
http://127.0.0.1:8000/docs

## Sample Input
{
  "message": "GET /admin HTTP/1.1 403",
  "service_name": "user-service",
  "event_type": "app_log"
}