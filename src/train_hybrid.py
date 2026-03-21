import pandas as pd
import numpy as np
import re
import os
import joblib

from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split, RandomizedSearchCV
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score

import matplotlib.pyplot as plt
import seaborn as sns


# ✅ ROOT PATH (IMPORTANT)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "data", "logs.csv")
ARTIFACTS_PATH = os.path.join(BASE_DIR, "artifacts")


def load_data(path):
    df = pd.read_csv(path)
    df.fillna("unknown", inplace=True)
    df['message'] = df['message'].astype(str)
    return df


def balance_rare_classes(df, min_samples=10):
    counts = df['severity'].value_counts()
    for cls, count in counts.items():
        if count < min_samples:
            needed = min_samples - count
            samples = df[df['severity'] == cls]
            df = pd.concat([df, samples.sample(needed, replace=True)], ignore_index=True)
    return df


def extract_features(df):
    df['status_code'] = df['message'].apply(
        lambda x: int(re.search(r'\b(\d{3})\b', x).group(1)) if re.search(r'\b(\d{3})\b', x) else 0
    )
    df['endpoint'] = df['message'].apply(
        lambda x: re.search(r'\"(GET|POST)\s(.*?)\sHTTP', x).group(2)
        if re.search(r'\"(GET|POST)\s(.*?)\sHTTP', x) else "unknown"
    )
    return df


def encode_structured(df):
    le_service = LabelEncoder()
    le_event = LabelEncoder()
    le_endpoint = LabelEncoder()
    le_severity = LabelEncoder()

    df['service_enc'] = le_service.fit_transform(df['service_name'])
    df['event_enc'] = le_event.fit_transform(df['event_type'])
    df['endpoint_enc'] = le_endpoint.fit_transform(df['endpoint'])

    y = le_severity.fit_transform(df['severity'])
    X_struct = df[['status_code', 'service_enc', 'event_enc', 'endpoint_enc']].values

    return X_struct, y, le_service, le_event, le_endpoint, le_severity


def split_and_vectorize(df, X_struct, y):
    X_train_struct, X_test_struct, y_train, y_test, df_train, df_test = train_test_split(
        X_struct, y, df, test_size=0.2, stratify=y, random_state=42
    )

    tfidf = TfidfVectorizer(max_features=500)

    X_train_text = tfidf.fit_transform(df_train['message']).toarray()
    X_test_text = tfidf.transform(df_test['message']).toarray()

    X_train = np.hstack((X_train_struct, X_train_text))
    X_test = np.hstack((X_test_struct, X_test_text))

    return X_train, X_test, y_train, y_test, tfidf


def scale_data(X_train, X_test):
    scaler = StandardScaler(with_mean=False)
    return scaler.fit_transform(X_train), scaler.transform(X_test), scaler


def train_models(X_train, y_train):
    models = {
        'logistic': LogisticRegression(max_iter=500, class_weight='balanced'),
        'rf': RandomForestClassifier(n_estimators=200, class_weight='balanced'),
        'xgb': XGBClassifier(eval_metric='mlogloss')
    }
    for model in models.values():
        model.fit(X_train, y_train)
    return models


def evaluate(models, X_test, y_test, label_encoder):
    for name, model in models.items():
        print(f"\n===== {name.upper()} =====")

        y_pred = model.predict(X_test)
        print("Accuracy:", accuracy_score(y_test, y_pred))

        labels = np.unique(y_test)

        print(classification_report(
            y_test, y_pred,
            labels=labels,
            target_names=label_encoder.inverse_transform(labels)
        ))

        cm = confusion_matrix(y_test, y_pred, labels=labels)
        sns.heatmap(cm, annot=True, fmt='d')
        plt.title(f"{name} Confusion Matrix")
        plt.show()


def tune_model(X_train, y_train):
    param_dist = {
        'n_estimators': [100, 200],
        'max_depth': [10, 20],
        'min_samples_split': [2, 5]
    }

    rf = RandomForestClassifier(class_weight='balanced')

    search = RandomizedSearchCV(
        rf, param_dist, n_iter=5, scoring='f1_weighted', cv=3
    )

    search.fit(X_train, y_train)

    print("Best Params:", search.best_params_)
    return search.best_estimator_


def save_all(model, scaler, tfidf, encoders):
    os.makedirs(ARTIFACTS_PATH, exist_ok=True)

    joblib.dump(model, os.path.join(ARTIFACTS_PATH, "modelhybrid.pkl"))
    joblib.dump(scaler, os.path.join(ARTIFACTS_PATH, "scalerhybrid.pkl"))
    joblib.dump(tfidf, os.path.join(ARTIFACTS_PATH, "tfidfhybrid.pkl"))
    joblib.dump(encoders, os.path.join(ARTIFACTS_PATH, "encodershybrid.pkl"))


def main():
    df = load_data(DATA_PATH)

    df = balance_rare_classes(df)
    df = extract_features(df)

    X_struct, y, le_service, le_event, le_endpoint, le_severity = encode_structured(df)

    X_train, X_test, y_train, y_test, tfidf = split_and_vectorize(df, X_struct, y)

    X_train, X_test, scaler = scale_data(X_train, X_test)

    models = train_models(X_train, y_train)

    evaluate(models, X_test, y_test, le_severity)

    best_model = tune_model(X_train, y_train)

    print("\n🔥 FINAL MODEL")
    evaluate({"Tuned RF": best_model}, X_test, y_test, le_severity)

    save_all(best_model, scaler, tfidf, {
        "service": le_service,
        "event": le_event,
        "endpoint": le_endpoint,
        "severity": le_severity
    })


if __name__ == "__main__":
    main()