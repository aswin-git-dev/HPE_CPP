# score_history.py
# Run once to back-fill anomaly scores for all training events
import sqlite3, joblib, json, numpy as np, sys
sys.path.insert(0, '.')
from feature_store import get_user_features, get_ip_features, init_db
from feature_engineer import parse_raw_log, engineer_features, features_to_vector
from train import normalize_score

init_db()

with open('models/latest.json') as f:
    ptr = json.load(f)
model = joblib.load(f'models/{ptr["model_file"]}')
with open(f'models/{ptr["meta_file"]}') as f:
    meta = json.load(f)

conn = sqlite3.connect('feature_store.db')
conn.row_factory = sqlite3.Row

while True:
    rows = conn.execute(
        'SELECT * FROM events WHERE anomaly_score IS NULL ORDER BY ts ASC LIMIT 500'
    ).fetchall()
    if not rows:
        print('All events scored.')
        break
    print(f'Scoring {len(rows)} events...')
    updated = 0
    for row in rows:
        try:
            raw = {
                'Timestamp (UTC)': row['ts'],
                'User / Subject':  row['user'],
                'Source IP':       row['source_ip'],
                'Namespace':       row['namespace'],
                'Object Type':     row['object_type'],
                'Method':          row['method'],
                'Result':          'Failure' if row['is_failed'] else 'Success',
                'Event Type':      'unknown',
            }
            parsed    = parse_raw_log(raw)
            user_hist = get_user_features(parsed['user'],     parsed['ts_dt'])
            ip_hist   = get_ip_features(parsed['source_ip'],  parsed['ts_dt'])
            feats     = engineer_features(parsed, user_hist, ip_hist)
            vec       = np.array([features_to_vector(feats)])
            score     = normalize_score(
                float(model.decision_function(vec)[0]),
                meta['score_stats']
            )
            conn.execute(
                'UPDATE events SET anomaly_score=?, model_version=? WHERE id=?',
                (score, meta['version'], row['id'])
            )
            updated += 1
        except Exception as e:
            continue
    conn.commit()
    print(f'  Updated {updated} events this batch.')

conn.close()
print('Done. Forensics queries will now return meaningful results.')