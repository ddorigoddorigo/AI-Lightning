#!/usr/bin/env python
import sys
sys.path.insert(0, '.')
from app import app

c = app.test_client()

# Test /api/nodes/online
print("Testing /api/nodes/online...")
resp = c.get('/api/nodes/online')
print(f"Status: {resp.status_code}")
if resp.status_code != 200:
    print(f"Error: {resp.data}")
else:
    print(f"OK: {resp.json}")

# Test /api/me with auth
print("\nTesting /api/me...")
resp = c.get('/api/me')
print(f"Status: {resp.status_code}")
if resp.status_code != 200:
    print(f"Error: {resp.data}")
