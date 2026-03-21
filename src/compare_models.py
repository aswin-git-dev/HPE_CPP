import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from sklearn.metrics import accuracy_score
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier

def compare_models(X_train, X_test, y_train, y_test):

    results = {}

    # Random Forest
    rf = RandomForestClassifier()
    rf.fit(X_train, y_train)
    y_pred_rf = rf.predict(X_test)
    results['RF'] = accuracy_score(y_test, y_pred_rf)

    # XGBoost
    xgb = XGBClassifier(eval_metric='mlogloss')
    xgb.fit(X_train, y_train)
    y_pred_xgb = xgb.predict(X_test)
    results['XGB'] = accuracy_score(y_test, y_pred_xgb)

    # Print
    for k,v in results.items():
        print(f"{k}: {v}")

    # Plot
    plt.bar(results.keys(), results.values())
    plt.title("Model Comparison")
    plt.xlabel("Models")
    plt.ylabel("Accuracy")
    plt.show()