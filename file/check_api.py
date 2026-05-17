import urllib.request
import urllib.parse
import http.cookiejar
import json

BASE = 'http://127.0.0.1:5000'

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def get(path):
    req = urllib.request.Request(BASE + path)
    with opener.open(req) as resp:
        return resp.read().decode('utf-8')

def post(path, data):
    data_bytes = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(BASE + path, data=data_bytes, headers={'Content-Type':'application/json'})
    with opener.open(req) as resp:
        return resp.read().decode('utf-8')

if __name__ == '__main__':
    print('GET /api/loads')
    print(get('/api/loads'))
    print('\nPOST /api/login')
    print(post('/api/login', {'email':'rahul@shipping.com', 'password':'password123'}))
    print('\nGET /api/me (with cookies)')
    print(get('/api/me'))
