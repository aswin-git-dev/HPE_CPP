import re
import numpy as np


def safe_transform(encoder, value):
    if value in encoder.classes_:
        return encoder.transform([value])[0]
    return -1  # unseen value


def rule_engine(log):
    message = log["message"]

    status = int(re.search(r'\b(\d{3})\b', message).group(1)) \
        if re.search(r'\b(\d{3})\b', message) else 0

    if "/admin" in message or "403" in message:
        return "unauthorized_access", "high"

    if status == 500:
        return "critical", "high"

    if status == 404:
        return "warning", "medium"

    return None, None


def preprocess_log(log, scaler, tfidf, encoders):

    def get_status(text):
        match = re.search(r'\b(\d{3})\b', text)
        return int(match.group(1)) if match else 0

    def get_endpoint(text):
        match = re.search(r'\"(GET|POST)\s(.*?)\sHTTP', text)
        return match.group(2) if match else "unknown"

    status = get_status(log["message"])

    # ✅ SAFE encoding (fix for unseen labels)
    service = safe_transform(encoders["service"], log["service_name"])
    event = safe_transform(encoders["event"], log["event_type"])
    endpoint = safe_transform(encoders["endpoint"], get_endpoint(log["message"]))

    text = tfidf.transform([log["message"]]).toarray()

    features = np.hstack(([status, service, event, endpoint], text[0]))

    return scaler.transform([features])


def hybrid_predict(log, model, scaler, tfidf, encoders):

    rule_label, risk = rule_engine(log)

    if rule_label:
        return {
            "prediction": rule_label,
            "source": "rule-based",
            "risk": risk
        }

    features = preprocess_log(log, scaler, tfidf, encoders)

    pred = model.predict(features)[0]
    label = encoders["severity"].inverse_transform([pred])[0]

    risk_map = {
        "info": "low",
        "warning": "medium",
        "critical": "high",
        "unauthorized_access": "critical"
    }

    return {
        "prediction": label,
        "source": "ml",
        "risk": risk_map[label]
    }