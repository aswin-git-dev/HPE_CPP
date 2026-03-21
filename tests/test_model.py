from src.predict import predict_log

def test_sample():
    sev, score = predict_log('GET /home HTTP/1.1" 200 OK', "web", "access")
    assert sev is not None