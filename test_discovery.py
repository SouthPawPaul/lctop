import lctop
try:
    url, port = lctop.discover_endpoint()
    print(f"Discovered URL: {url}")
    print(f"Discovered Port: {port}")
    print(f"Endpoint: {url.rstrip('/')}:{port}/slots")
except Exception as e:
    print(f"Failed: {e}")
