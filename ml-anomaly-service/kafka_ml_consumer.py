import json
from datetime import datetime, timezone

import requests
from kafka import KafkaConsumer

import smtplib
from email.message import EmailMessage

SENDER_EMAIL = "gayathribalaji2242@gmail.com"
SENDER_APP_PASSWORD = "vrjk mwcj bauc pmta"
RECEIVER_EMAIL = "bgayathri1@student.tce.edu"

KAFKA_TOPIC = "k8s-audit-raw"
KAFKA_BOOTSTRAP = "localhost:9092"

ML_API_URL = "http://localhost:8000/score"

OPENSEARCH_URL = "http://localhost:9200"
OPENSEARCH_INDEX = "security-anomalies"


def map_audit_to_ml_input(audit_event):
    user = audit_event.get("user", {})
    object_ref = audit_event.get("objectRef", {})
    response_status = audit_event.get("responseStatus", {})
    source_ips = audit_event.get("sourceIPs", [])

    status_code = response_status.get("code", 200)
    result = "Success" if int(status_code) < 400 else "Failure"

    return {
        "user_subject": user.get("username", "unknown"),
        "method": audit_event.get("verb", "unknown"),
        "object_type": object_ref.get("resource", "unknown"),
        "namespace": object_ref.get("namespace", "default"),
        "source_ip": source_ips[0] if source_ips else "unknown",
        "result": result,
        "timestamp_utc": audit_event.get(
            "requestReceivedTimestamp",
            audit_event.get("stageTimestamp", "")
        ),
        "object_name": object_ref.get("name", ""),
        "event_type": audit_event.get("stage", "unknown"),
        "classification": audit_event.get("level", "Metadata"),
        "requesting_service": audit_event.get("userAgent", "unknown")
    }


def store_in_opensearch(audit_event, ml_input, scored_event):
    document = {
        "@timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_audit_event": audit_event,
        "ml_input": ml_input,
        "ml_output": scored_event,
        "risk_level": scored_event.get("risk_level"),
        "anomaly_score": scored_event.get("anomaly_score"),
        "reason": scored_event.get("reason"),
        "user": scored_event.get("user", ml_input.get("user_subject")),
        "namespace": ml_input.get("namespace"),
        "method": ml_input.get("method"),
        "object_type": ml_input.get("object_type"),
        "source_ip": ml_input.get("source_ip")
    }

    url = f"{OPENSEARCH_URL}/{OPENSEARCH_INDEX}/_doc"

    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(document),
        timeout=10
    )

    if response.status_code in [200, 201]:
        print("Stored in OpenSearch index:", OPENSEARCH_INDEX)
    else:
        print("OpenSearch store error:", response.status_code, response.text)


def send_alert(scored_event, ml_input):
    if scored_event.get("risk_level") == "HIGH":
        with open("alerts.log", "a", encoding="utf-8") as f:
            f.write("HIGH RISK ALERT\n")
            f.write(f"User: {ml_input.get('user_subject')}\n")
            f.write(f"Resource: {ml_input.get('object_type')}\n")
            f.write(f"Score: {scored_event.get('anomaly_score')}\n")
            f.write(f"Reason: {scored_event.get('reason')}\n")
            f.write("-------------------------\n")
        print("HIGH risk alert generated in alerts.log")

def send_email_alert(scored_event, ml_input):
    if scored_event.get("risk_level") != "HIGH":
        return

    subject = "🚨 HIGH Risk Security Alert Detected"

    body = f"""
SECURITY ALERT - HIGH RISK ACTIVITY DETECTED

Risk Level: {scored_event.get("risk_level")}
Anomaly Score: {scored_event.get("anomaly_score")}

User:
{ml_input.get("user_subject")}

Source IP:
{ml_input.get("source_ip")}

Namespace:
{ml_input.get("namespace")}

Resource:
{ml_input.get("object_type")}

Action:
{ml_input.get("method")}

Object Name:
{ml_input.get("object_name")}

Time:
{ml_input.get("timestamp_utc")}

Reason:
{scored_event.get("reason")}

Recommended Action:
Please review the Kubernetes audit logs and verify whether this activity is authorized.

This alert was generated automatically by the Smart Security Logging Framework.
"""

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            smtp.send_message(msg)

        print("Email alert sent to:", RECEIVER_EMAIL)

    except Exception as e:
        print("Email alert failed:", e)

consumer = KafkaConsumer(
    KAFKA_TOPIC,
    bootstrap_servers=KAFKA_BOOTSTRAP,
    value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    auto_offset_reset="latest",
    group_id="ml-consumer-group"
)

print("ML Kafka Consumer started...")
print(f"Listening to Kafka topic: {KAFKA_TOPIC}")
print(f"OpenSearch index: {OPENSEARCH_INDEX}")

for message in consumer:
    audit_event = message.value

    print("\n==============================")
    print("Received raw audit event:")
    print("Verb:", audit_event.get("verb"))
    print("URI:", audit_event.get("requestURI"))

    ml_input = map_audit_to_ml_input(audit_event)

    print("\nMapped ML input:")
    print(json.dumps(ml_input, indent=2))

    try:
        response = requests.post(ML_API_URL, json=ml_input, timeout=10)

        if response.status_code == 200:
            scored_event = response.json()

            print("\nML Scored Output:")
            print("Risk Level:", scored_event.get("risk_level"))
            print("Anomaly Score:", scored_event.get("anomaly_score"))
            print("Reason:", scored_event.get("reason"))

            store_in_opensearch(audit_event, ml_input, scored_event)
            send_alert(scored_event, ml_input)
            send_email_alert(scored_event, ml_input)

        else:
            print("ML API error:", response.status_code, response.text)

    except Exception as e:
        print("Error in ML/OpenSearch pipeline:", e)