import json
import os
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from kafka import KafkaConsumer

load_dotenv()

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:19092")
KAFKA_TOPICS = ["k8s-audit-raw", "falco-alerts"]

ML_API_URL = os.getenv("ML_API_URL", "http://localhost:8000/score")
OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "security-anomalies")

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
ENABLE_SLACK_ALERTS = os.getenv("ENABLE_SLACK_ALERTS", "true").lower() == "true"

MIN_ALERT_SCORE = float(os.getenv("MIN_ALERT_SCORE", "0.95"))

CRITICAL_ACTIONS = {
    "delete",
    "patch",
    "exec",
    "create"
}

CRITICAL_RESOURCES = {
    "secrets",
    "secret",
    "clusterrolebindings",
    "clusterrolebinding",
    "rolebindings",
    "rolebinding",
    "pods/exec",
    "runtime_event"
}

CRITICAL_FALCO_KEYWORDS = {
    "shell",
    "terminal",
    "passwd",
    "shadow",
    "sensitive",
    "privilege",
    "write below",
    "unexpected"
}

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
        "namespace": object_ref.get("namespace") or "cluster-wide",
        "source_ip": source_ips[0] if source_ips else "unknown",
        "result": result,
        "timestamp_utc": audit_event.get(
            "requestReceivedTimestamp",
            audit_event.get("stageTimestamp", "")
        ),
        "object_name": object_ref.get("name") or "N/A",
        "event_type": "k8s_audit",
        "classification": audit_event.get("level", "Metadata"),
        "requesting_service": audit_event.get("userAgent", "unknown")
    }


def map_falco_to_ml_input(falco_event):
    output_fields = falco_event.get("output_fields", {})

    return {
        "user_subject": output_fields.get("user.name", "unknown"),
        "method": falco_event.get("rule", "unknown"),
        "object_type": "runtime_event",
        "namespace": output_fields.get("k8s.ns.name", "default") or "default",
        "source_ip": output_fields.get("fd.name", "unknown"),
        "result": "Success",
        "timestamp_utc": falco_event.get("time", ""),
        "object_name": output_fields.get("k8s.pod.name", ""),
        "event_type": "falco",
        "classification": falco_event.get("priority", "Notice"),
        "requesting_service": output_fields.get("proc.name", "unknown")
    }


def normalize_kafka_message(topic, kafka_message):
    if topic == "k8s-audit-raw":
        raw_event = kafka_message.get("event", kafka_message) if isinstance(kafka_message, dict) else kafka_message
        ml_input = map_audit_to_ml_input(raw_event)
        return raw_event, ml_input

    if topic == "falco-alerts":
        raw_event = kafka_message
        ml_input = map_falco_to_ml_input(raw_event)
        return raw_event, ml_input

    return None, None


def store_in_opensearch(raw_event, ml_input, scored_event, source_topic):
    document = {
        "@timestamp": datetime.now(timezone.utc).isoformat(),
        "source_topic": source_topic,
        "source_type": ml_input.get("event_type"),
        "raw_event": raw_event,
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

    response = requests.post(
        f"{OPENSEARCH_URL}/{OPENSEARCH_INDEX}/_doc",
        headers={"Content-Type": "application/json"},
        data=json.dumps(document),
        timeout=10
    )

    if response.status_code in [200, 201]:
        print("Stored in OpenSearch index:", OPENSEARCH_INDEX)
    else:
        print("OpenSearch store error:", response.status_code, response.text)

def should_send_critical_alert(scored_event, ml_input):
    score = float(scored_event.get("anomaly_score", 0) or 0)
    risk_level = scored_event.get("risk_level", "")
    method = str(ml_input.get("method", "")).lower()
    object_type = str(ml_input.get("object_type", "")).lower()
    event_type = str(ml_input.get("event_type", "")).lower()
    reason = str(scored_event.get("reason", "")).lower()

    if risk_level != "HIGH":
        return False

    if score < MIN_ALERT_SCORE:
        print(f"Alert skipped: score {score} is below threshold {MIN_ALERT_SCORE}")
        return False

    if event_type == "falco":
        if any(keyword in method for keyword in CRITICAL_FALCO_KEYWORDS):
            return True
        if any(keyword in reason for keyword in CRITICAL_FALCO_KEYWORDS):
            return True
        print("Alert skipped: Falco event is HIGH but not critical runtime activity")
        return False

    action_is_critical = method in CRITICAL_ACTIONS
    resource_is_critical = any(resource in object_type for resource in CRITICAL_RESOURCES)

    if action_is_critical and resource_is_critical:
        return True

    print(
        "Alert skipped: HIGH score but not critical action/resource "
        f"(method={method}, object_type={object_type}, score={score})"
    )
    return False

def write_local_alert_log(scored_event, ml_input):
    if not should_send_critical_alert(scored_event, ml_input):
        return

    with open("alerts.log", "a", encoding="utf-8") as f:
        f.write("HIGH RISK ALERT\n")
        f.write(f"Source: {ml_input.get('event_type')}\n")
        f.write(f"User: {ml_input.get('user_subject')}\n")
        f.write(f"Resource: {ml_input.get('object_type')}\n")
        f.write(f"Action/Rule: {ml_input.get('method')}\n")
        f.write(f"Score: {scored_event.get('anomaly_score')}\n")
        f.write(f"Reason: {scored_event.get('reason')}\n")
        f.write("-------------------------\n")

    print("HIGH risk alert generated in alerts.log")


def send_slack_alert(scored_event, ml_input):
    if not should_send_critical_alert(scored_event, ml_input):
        return

    if not ENABLE_SLACK_ALERTS:
        print("Slack alerts are disabled")
        return

    if not SLACK_WEBHOOK_URL:
        print("Slack webhook URL missing. Add SLACK_WEBHOOK_URL in .env")
        return

    payload = {
        "text": (
            "🚨 *HIGH Risk Security Alert Detected*\n\n"
            f"*Source:* `{ml_input.get('event_type')}`\n"
            f"*Risk Level:* `{scored_event.get('risk_level')}`\n"
            f"*Anomaly Score:* `{scored_event.get('anomaly_score')}`\n"
            f"*User:* `{ml_input.get('user_subject')}`\n"
            f"*Source IP:* `{ml_input.get('source_ip')}`\n"
            f"*Namespace:* `{ml_input.get('namespace')}`\n"
            f"*Resource:* `{ml_input.get('object_type')}`\n"
            f"*Action / Falco Rule:* `{ml_input.get('method')}`\n"
            f"*Object / Pod:* `{ml_input.get('object_name')}`\n"
            f"*Time:* `{ml_input.get('timestamp_utc')}`\n\n"
            f"*Reason:*\n{scored_event.get('reason')}\n\n"
            "*Recommended Action:*\n"
            "Review Kubernetes audit logs, Falco runtime alerts, and OpenSearch dashboard.\n\n"
            "_Generated automatically by Smart Security Logging Framework._"
        )
    }

    try:
        response = requests.post(
            SLACK_WEBHOOK_URL,
            json=payload,
            timeout=10
        )

        if response.status_code == 200:
            print("Slack alert sent successfully")
        else:
            print("Slack alert failed:", response.status_code, response.text)

    except Exception as e:
        print("Slack alert error:", e)


consumer = KafkaConsumer(
    *KAFKA_TOPICS,
    bootstrap_servers=KAFKA_BOOTSTRAP,
    value_deserializer=lambda m: json.loads(m.decode("utf-8")),
    auto_offset_reset="latest",
    group_id="event-consumer-group"
)

print("Security Event Processor started...")
print(f"Listening to Kafka topics: {', '.join(KAFKA_TOPICS)}")
print(f"OpenSearch index: {OPENSEARCH_INDEX}")
print("Slack alerts:", "enabled" if ENABLE_SLACK_ALERTS else "disabled")

for message in consumer:
    topic = message.topic
    kafka_message = message.value

    raw_event, ml_input = normalize_kafka_message(topic, kafka_message)

    if raw_event is None or ml_input is None:
        print("Skipping unknown topic:", topic)
        continue

    print("\n==============================")
    print("Received event from topic:", topic)
    print("Source type:", ml_input.get("event_type"))
    print("Action/Rule:", ml_input.get("method"))
    print("Namespace:", ml_input.get("namespace"))

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

            store_in_opensearch(raw_event, ml_input, scored_event, topic)
            write_local_alert_log(scored_event, ml_input)
            send_slack_alert(scored_event, ml_input)

        else:
            print("ML API error:", response.status_code, response.text)

    except Exception as e:
        print("Error in ML/OpenSearch/Slack pipeline:", e)