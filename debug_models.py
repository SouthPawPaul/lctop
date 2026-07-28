import urllib.request
import json

url = "http://127.0.0.1:8080/models"
try:
    with urllib.request.urlopen(url) as response:
        data = json.load(response)
        print(f"Type: {type(data)}")
        print(f"Content: {data}")
except Exception as e:
    print(f"Error: {e}")
