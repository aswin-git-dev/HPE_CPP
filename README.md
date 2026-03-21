# Hybrid Log Anomaly Detection System

## Overview

This project detects anomalies in system logs using a hybrid machine learning approach combining:

* Isolation Forest (unsupervised anomaly detection)
* XGBoost (supervised classification)

## Key Features

* Extracts structured + text features from logs
* Uses TF-IDF for log message processing
* Adds anomaly score as feature
* Improves classification accuracy

## Models Used

* Isolation Forest
* XGBoost Classifier

## Workflow

1. Log preprocessing
2. Feature extraction (status, endpoint)
3. TF-IDF vectorization
4. Isolation Forest anomaly scoring
5. XGBoost classification

## Run Instructions

pip install -r requirements.txt
python src/train.py

## Author

Navina M
