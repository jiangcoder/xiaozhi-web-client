from flask import Flask, render_template, jsonify
import os
import uuid
from dotenv import load_dotenv
import websockets
import asyncio
import json
import threading
import multiprocessing
import atexit
from proxy import WebSocketProxy  # 导入 proxy.py 中的 WebSocketProxy 类

load_dotenv()

app = Flask(__name__, static_url_path='/static')

# 配置
WS_URL = os.getenv("WS_URL", "ws://10.1.5.14:9005")
PROXY_URL = "ws://localhost:5002"  # WebSocket代理地址
TOKEN = os.getenv("DEVICE_TOKEN", "123")
proxy_process = None

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

def cleanup():
    """清理进程"""
    global proxy_process
    if proxy_process:
        proxy_process.terminate()
        proxy_process.join()
        proxy_process = None

def run_proxy():
    """在单独的进程中运行proxy服务器"""
    proxy = WebSocketProxy()
    asyncio.run(proxy.main())

if __name__ == '__main__':
    # 注册退出时的清理函数
    atexit.register(cleanup)
    
    device_id = get_mac_address()
    print(f"Device ID: {device_id}")
    print(f"Token: {TOKEN}")
    print(f"WS URL: {WS_URL}")
    print(f"Proxy URL: {PROXY_URL}")
    
    # 在单独的进程中启动proxy服务器
    proxy_process = multiprocessing.Process(target=run_proxy)
    proxy_process.start()
    print("Proxy server started in background process")
    
    print("Starting web server...")
    # 禁用调试模式运行Flask
    app.run(host='0.0.0.0', port=5001, debug=False) 