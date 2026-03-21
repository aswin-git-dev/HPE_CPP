import pandas as pd
import numpy as np
import joblib

from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split

from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from src.preprocess import get_status, get_endpoint


# =========================================
# LOAD DATA
# =========================================
df = pd.read_csv("data/data.csv")
df.fillna("unknown", inplace=True)
df['message'] = df['message'].astype(str)


# =========================================
# FEATURE EXTRACTION
# =========================================
df['status_code'] = df['message'].apply(get_status)
df['endpoint'] = df['message'].apply(get_endpoint)


# =========================================
# ENCODING
# =========================================
le_service = LabelEncoder()
le_event = LabelEncoder()
le_endpoint = LabelEncoder()
le_severity = LabelEncoder()

df['service_enc'] = le_service.fit_transform(df['service_name'])
df['event_enc'] = le_event.fit_transform(df['event_type'])
df['endpoint_enc'] = le_endpoint.fit_transform(df['endpoint'])

# Remove single class
class_counts = df['severity'].value_counts()
single_classes = class_counts[class_counts == 1].index.tolist()
df = df[~df['severity'].isin(single_classes)]

y = le_severity.fit_transform(df['severity'])

X_struct = df[['status_code','service_enc','event_enc','endpoint_enc']].values


# =========================================
# SPLIT + TFIDF
# =========================================
X_train_s, X_test_s, y_train, y_test, df_train, df_test = train_test_split(
    X_struct, y, df, test_size=0.2, stratify=y, random_state=42
)

tfidf = TfidfVectorizer(max_features=500)

X_train_text = tfidf.fit_transform(df_train['message']).toarray()
X_test_text = tfidf.transform(df_test['message']).toarray()

X_train = np.hstack((X_train_s, X_train_text))
X_test = np.hstack((X_test_s, X_test_text))


# =========================================
# SCALING
# =========================================
scaler = StandardScaler(with_mean=False)
X_train = scaler.fit_transform(X_train)
X_test = scaler.transform(X_test)


# =========================================
# ISOLATION FOREST
# =========================================
iso = IsolationForest(contamination=0.05, random_state=42)
iso.fit(X_train)

train_score = iso.decision_function(X_train).reshape(-1,1)
test_score = iso.decision_function(X_test).reshape(-1,1)

X_train = np.hstack((X_train, train_score))
X_test = np.hstack((X_test, test_score))


# =========================================
# RANDOM FOREST MODEL
# =========================================
rf = RandomForestClassifier(n_estimators=100, random_state=42)
rf.fit(X_train, y_train)


# =========================================
# EVALUATION
# =========================================
y_pred = rf.predict(X_test)

print("IF + RF Accuracy:", accuracy_score(y_test, y_pred))
print(classification_report(y_test, y_pred))
print("Confusion Matrix:\n", confusion_matrix(y_test, y_pred))


# =========================================
# SAVE
# =========================================
joblib.dump(rf, "models/rf_model.pkl")
joblib.dump(iso, "models/iso_rf.pkl")

print("✅ IF + RF model saved!")