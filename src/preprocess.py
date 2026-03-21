import re

def get_status(text):
    match = re.search(r'\b(\d{3})\b', text)
    return int(match.group(1)) if match else 0

def get_endpoint(text):
    match = re.search(r'\"(GET|POST)\s(.*?)\sHTTP', text)
    return match.group(2) if match else "unknown"