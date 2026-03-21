import pandas as pd
import numpy as np
import joblib
import matplotlib.pyplot as plt
from sklearn.metrics import confusion_matrix
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.ensemble import IsolationForest
from xgboost import XGBClassifier
from sklearn.metrics import classification_report, accuracy_score

from src.preprocess import get_status, get_endpoint

# LOAD
df = pd.read_csv("data/data.csv")
df.fillna("unknown", inplace=True)
df['message'] = df['message'].astype(str)

# FEATURE
df['status_code'] = df['message'].apply(get_status)
df['endpoint'] = df['message'].apply(get_endpoint)

# ENCODING
le_service = LabelEncoder()
le_event = LabelEncoder()
le_endpoint = LabelEncoder()
le_severity = LabelEncoder()

df['service_enc'] = le_service.fit_transform(df['service_name'])
df['event_enc'] = le_event.fit_transform(df['event_type'])
df['endpoint_enc'] = le_endpoint.fit_transform(df['endpoint'])

# REMOVE SINGLE CLASS
class_counts = df['severity'].value_counts()
single_member_classes = class_counts[class_counts == 1].index.tolist()
df = df[~df['severity'].isin(single_member_classes)]

y = le_severity.fit_transform(df['severity'])
X_struct = df[['status_code','service_enc','event_enc','endpoint_enc']].values

# SPLIT
X_train_s, X_test_s, y_train, y_test, df_train, df_test = train_test_split(
    X_struct, y, df, test_size=0.2, stratify=y, random_state=42
)

# TFIDF
tfidf = TfidfVectorizer(max_features=500)
X_train_text = tfidf.fit_transform(df_train['message']).toarray()
X_test_text = tfidf.transform(df_test['message']).toarray()

X_train = np.hstack((X_train_s, X_train_text))
X_test = np.hstack((X_test_s, X_test_text))

# SCALE
scaler = StandardScaler(with_mean=False)
X_train = scaler.fit_transform(X_train)
X_test = scaler.transform(X_test)

# ISOLATION
iso = IsolationForest(contamination=0.05, random_state=42)
iso.fit(X_train)

train_score = iso.decision_function(X_train).reshape(-1,1)
test_score = iso.decision_function(X_test).reshape(-1,1)

X_train = np.hstack((X_train, train_score))
X_test = np.hstack((X_test, test_score))

# MODEL
model = XGBClassifier(eval_metric='mlogloss')
model.fit(X_train, y_train)

# EVAL
y_pred = model.predict(X_test)
print("Accuracy:", accuracy_score(y_test, y_pred))
print(classification_report(y_test, y_pred))

# SAVE
joblib.dump(model, "models/model.pkl")
joblib.dump(scaler, "scaler.pkl")
joblib.dump(tfidf, "tfidf.pkl")
joblib.dump(iso, "isolation.pkl")

joblib.dump({
    "service": le_service,
    "event": le_event,
    "endpoint": le_endpoint,
    "severity": le_severity
}, "encoders.pkl")

# Confusion Matrix
cm = confusion_matrix(y_test, y_pred)
print("Confusion Matrix:\n", cm)

# Plot anomaly scores
plt.hist(test_score, bins=50)
plt.title("Anomaly Score Distribution")
plt.xlabel("Score")
plt.ylabel("Frequency")
plt.show()