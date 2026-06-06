import json
from kafka import KafkaProducer

producer = KafkaProducer(
    bootstrap_servers="localhost:9092",
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

event = {
    "user_subject": "john.doe",
    "method": "list",
    "object_type": "secrets",
    "namespace": "prod",
    "source_ip": "unknown",
    "result": "Success",
    "timestamp_utc": "2026-05-29T02:14:00Z"
}

producer.send("security-logs", event)
producer.flush()

print("Event sent to Kafka")