#!/usr/bin/env python3
import redis
r = redis.from_url('redis://localhost:6379/0')
nodes = r.keys('node:*')
print('Connected nodes:', nodes)
for n in nodes:
    data = r.hgetall(n)
    print(f'{n}: {data}')

# Check websocket nodes
ws_nodes = r.keys('ws_node:*')
print('WebSocket nodes:', ws_nodes)
for n in ws_nodes:
    data = r.hgetall(n)
    print(f'{n}: {data}')
