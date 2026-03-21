import joblib
import numpy as np
from src.preprocess import get_status, get_endpoint

model = joblib.load("models/model.pkl")
scaler = joblib.load("scaler.pkl")
tfidf = joblib.load("tfidf.pkl")
iso = joblib.load("isolation.pkl")
enc = joblib.load("encoders.pkl")

def predict_log(message, service, event):
    status = get_status(message)
    endpoint = get_endpoint(message)

    le_service = enc["service"]
    le_event = enc["event"]
    le_endpoint = enc["endpoint"]
    le_severity = enc["severity"]

    service_enc = le_service.transform([service])[0] if service in le_service.classes_ else 0
    event_enc = le_event.transform([event])[0] if event in le_event.classes_ else 0
    endpoint_enc = le_endpoint.transform([endpoint])[0] if endpoint in le_endpoint.classes_ else 0

    X_struct = np.array([[status, service_enc, event_enc, endpoint_enc]])
    X_text = tfidf.transform([message]).toarray()

    X = np.hstack((X_struct, X_text))
    X = scaler.transform(X)

    score = iso.decision_function(X).reshape(-1,1)
    X = np.hstack((X, score))

    pred = model.predict(X)[0]
    severity = le_severity.inverse_transform([pred])[0]

    return severity, score[0][0]