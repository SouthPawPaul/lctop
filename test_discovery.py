import lctop
try:
    url, port, model_id = lctop.discover_endpoint()
    print(f"Discovered URL: {url}")
    print(f"Discovered Port: {port}")
    print(f"Discovered Model: {model_id}")
    print(f"Endpoint: {url.rstrip('/')}:{port}/slots?model={model_id}")
except Exception as e:
    print(f"Failed: {e}")
