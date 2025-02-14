from flask import Flask, render_template, jsonify
import os
import uuid
from dotenv import load_dotenv
import websockets
import asyncio
import json

load_dotenv()

app = Flask(__name__, static_url_path='/static')

# 配置
WS_URL = os.getenv("WS_URL", "ws://10.1.5.14:9005")
PROXY_URL = "ws://localhost:5002"  # WebSocket代理地址
TOKEN = os.getenv("DEVICE_TOKEN", "123")

def get_mac_address():
    mac = uuid.getnode()
    return ':'.join(['{:02x}'.format((mac >> elements) & 0xff) for elements in range(0,8*6,8)][::-1])

async def test_websocket_connection():
    """测试WebSocket连接"""
    try:
        # 测试代理连接
        async with websockets.connect(PROXY_URL) as ws:
            await ws.close()
            return True, None
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    device_id = get_mac_address()
    token = os.getenv("DEVICE_TOKEN", "123")
    ws_url = f"ws://localhost:5002"  # 代理服务器地址
    return render_template('index.html', device_id=device_id, token=token, ws_url=ws_url)

@app.route('/test_connection', methods=['GET'])
def test_connection():
    try:
        device_id = get_mac_address()
        success, error = asyncio.run(test_websocket_connection())
        
        if success:
            return jsonify({
                'status': 'success',
                'message': '连接测试成功',
                'device_id': device_id,
                'token': TOKEN,
                'ws_url': PROXY_URL
            })
        else:
            return jsonify({
                'status': 'error',
                'message': f'连接测试失败: {error}'
            }), 500
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    device_id = get_mac_address()
    print(f"Device ID: {device_id}")
    print(f"Token: {TOKEN}")
    print(f"WS URL: {WS_URL}")
    print(f"Proxy URL: {PROXY_URL}")
    print("Starting server...")
    app.run(host='0.0.0.0', port=5001, debug=True) 