import asyncio
import websockets
import os
import json
from dotenv import load_dotenv
import uuid
import opuslib
import wave
import io
import numpy as np

load_dotenv()

# 配置
WS_URL = os.getenv("WS_URL")
if not WS_URL:
    print("警告: 未设置WS_URL环境变量，请检查.env文件")
    WS_URL = "ws://localhost:9005"  # 默认值改为localhost

TOKEN = os.getenv("DEVICE_TOKEN")
if not TOKEN:
    print("警告: 未设置DEVICE_TOKEN环境变量，请检查.env文件")
    TOKEN = "123"  # 默认值

PROXY_PORT = int(os.getenv("PROXY_PORT", "5002"))

def get_mac_address():
    mac = uuid.getnode()
    return ':'.join(['{:02x}'.format((mac >> elements) & 0xff) for elements in range(0,8*6,8)][::-1])

def pcm_to_opus(pcm_data):
    """将PCM音频数据转换为Opus格式"""
    try:
        # 创建编码器：16kHz, 单声道, VOIP模式
        encoder = opuslib.Encoder(16000, 1, 'voip')
        
        try:
            # 确保PCM数据是Int16格式
            pcm_array = np.frombuffer(pcm_data, dtype=np.int16)
            
            # 编码PCM数据，每帧960个采样点
            opus_data = encoder.encode(pcm_array.tobytes(), 960)  # 60ms at 16kHz
            return opus_data
            
        except opuslib.OpusError as e:
            print(f"Opus编码错误: {e}, 数据长度: {len(pcm_data)}")
            return None
            
    except Exception as e:
        print(f"Opus初始化错误: {e}")
        return None

def opus_to_wav(opus_data):
    """将Opus音频数据转换为WAV格式"""
    try:
        # 创建解码器：16kHz, 单声道
        decoder = opuslib.Decoder(16000, 1)
        
        try:
            # 解码Opus数据
            pcm_data = decoder.decode(opus_data, 960)  # 使用960采样点
            if pcm_data:
                # 创建WAV文件头
                wav_io = io.BytesIO()
                with wave.open(wav_io, 'wb') as wav:
                    wav.setnchannels(1)  # 单声道
                    wav.setsampwidth(2)  # 16位
                    wav.setframerate(16000)  # 16kHz
                    wav.writeframes(pcm_data)
                return wav_io.getvalue()
            return None
            
        except opuslib.OpusError as e:
            print(f"Opus解码错误: {e}, 数据长度: {len(opus_data)}")
            return None
            
    except Exception as e:
        print(f"Opus初始化错误: {e}")
        return None

class WebSocketProxy:
    def __init__(self):
        self.device_id = get_mac_address()
        self.headers = {
            'Authorization': f'Bearer {TOKEN}',
            'device-id': self.device_id
        }

    async def proxy_handler(self, websocket):
        """处理来自浏览器的WebSocket连接"""
        try:
            print(f"New client connection from {websocket.remote_address}")
            async with websockets.connect(WS_URL, extra_headers=self.headers) as server_ws:
                print(f"Connected to server with headers: {self.headers}")
                
                # 创建任务
                client_to_server = asyncio.create_task(self.handle_client_messages(websocket, server_ws))
                server_to_client = asyncio.create_task(self.handle_server_messages(server_ws, websocket))
                
                # 等待任意一个任务完成
                done, pending = await asyncio.wait(
                    [client_to_server, server_to_client],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # 取消其他任务
                for task in pending:
                    task.cancel()
                    
        except Exception as e:
            print(f"Proxy error: {e}")
        finally:
            print("Client connection closed")

    async def handle_server_messages(self, server_ws, client_ws):
        """处理来自服务器的消息"""
        try:
            async for message in server_ws:
                if isinstance(message, str):
                    print(f"Server text message: {message}")
                    await client_ws.send(message)
                else:
                    print("Server binary message (audio)")
                    wav_data = opus_to_wav(message)
                    if wav_data:
                        await client_ws.send(wav_data)
                    else:
                        print("音频解码失败")
        except Exception as e:
            print(f"Server message handling error: {e}")

    async def handle_client_messages(self, client_ws, server_ws):
        """处理来自客户端的消息"""
        try:
            async for message in client_ws:
                if isinstance(message, str):
                    print(f"Client text message: {message}")
                    await server_ws.send(message)
                else:
                    print("Client binary message (audio)")
                    # 直接发送PCM数据，不转换为Opus格式
                    await server_ws.send(message)
        except Exception as e:
            print(f"Client message handling error: {e}")

    async def main(self):
        """启动代理服务器"""
        print(f"Starting proxy server...")
        print(f"Device ID: {self.device_id}")
        print(f"Token: {TOKEN}")
        print(f"Target WS URL: {WS_URL}")
        
        server = await websockets.serve(self.proxy_handler, "0.0.0.0", PROXY_PORT)
        print(f"Proxy server is listening on ws://0.0.0.0:{PROXY_PORT}")
        await asyncio.Future()  # 运行forever

if __name__ == "__main__":
    proxy = WebSocketProxy()
    asyncio.run(proxy.main())