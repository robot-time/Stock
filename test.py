import base64
import json

# Read your Firebase credentials file
with open('FakeStockSim Firebase Service Account.json', 'r') as f:
    cred_data = json.load(f)

# Convert to base64
cred_base64 = base64.b64encode(json.dumps(cred_data).encode('utf-8')).decode('utf-8')
print(cred_base64)