#!/usr/bin/env python3
import json, urllib.request
BASE='http://localhost:8000'
req=urllib.request.Request(BASE+'/api/benchmark/run', data=b'{}', headers={'Content-Type':'application/json'}, method='POST')
print(json.dumps(json.load(urllib.request.urlopen(req)), ensure_ascii=False, indent=2))
