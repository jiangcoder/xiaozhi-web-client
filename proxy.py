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
WS_URL = os.getenv("WS_URL", "ws://10.1.5.14:9005")
TOKEN = os.getenv("DEVICE_TOKEN", "123")

def get_mac_address():
    mac = uuid.getnode()
    return ':'.join(['{:02x}'.format((mac >> elements) & 0xff) for elements in range(0,8*6,8)][::-1])

def opus_to_wav(opus_data):
    """将Opus音频数据转换为WAV格式"""
    try:
        # 创建解码器：16kHz, 单声道
        decoder = opuslib.Decoder(16000, 1)
        
        try:
            # 解码Opus数据
            pcm_data = decoder.decode(opus_data, 960)  # 使用960采样点
            return pcm_data
            
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
        self.pcm_buffer = bytearray()  # 用于缓存PCM数据
        self.last_message_time = 0  # 上次收到消息的时间
        self.buffer_timeout = 0.5  # 缓冲区超时时间（秒）
        
    def create_wav_header(self, data_size):
        """创建WAV文件头"""
        header = bytearray()
        # RIFF头
        header.extend(b'RIFF')
        header.extend((data_size + 36).to_bytes(4, 'little'))  # 文件大小
        header.extend(b'WAVE')
        
        # fmt子块
        header.extend(b'fmt ')
        header.extend((16).to_bytes(4, 'little'))  # Subchunk1Size
        header.extend((1).to_bytes(2, 'little'))   # AudioFormat (PCM)
        header.extend((1).to_bytes(2, 'little'))   # NumChannels
        header.extend((16000).to_bytes(4, 'little'))  # SampleRate
        header.extend((32000).to_bytes(4, 'little'))  # ByteRate
        header.extend((2).to_bytes(2, 'little'))   # BlockAlign
        header.extend((16).to_bytes(2, 'little'))  # BitsPerSample
        
        # data子块
        header.extend(b'data')
        header.extend(data_size.to_bytes(4, 'little'))  # 数据大小
        
        return header
        
    async def send_buffer(self, client_ws):
        """发送缓冲区数据"""
        if len(self.pcm_buffer) > 0:
            wav_header = self.create_wav_header(len(self.pcm_buffer))
            wav_data = wav_header + self.pcm_buffer
            await client_ws.send(wav_data)
            self.pcm_buffer = bytearray()
            
    async def check_buffer_timeout(self, client_ws):
        """检查缓冲区是否超时"""
        while True:
            await asyncio.sleep(0.1)  # 每100ms检查一次
            current_time = asyncio.get_event_loop().time()
            if len(self.pcm_buffer) > 0 and (current_time - self.last_message_time) > self.buffer_timeout:
                await self.send_buffer(client_ws)

    async def proxy_handler(self, websocket):
        """处理来自浏览器的WebSocket连接"""
        try:
            print(f"New client connection from {websocket.remote_address}")
            async with websockets.connect(WS_URL, extra_headers=self.headers) as server_ws:
                print(f"Connected to server with headers: {self.headers}")
                
                # 创建任务
                client_to_server = asyncio.create_task(self.handle_client_messages(websocket, server_ws))
                server_to_client = asyncio.create_task(self.handle_server_messages(server_ws, websocket))
                buffer_checker = asyncio.create_task(self.check_buffer_timeout(websocket))
                
                # 等待任意一个任务完成
                done, pending = await asyncio.wait(
                    [client_to_server, server_to_client, buffer_checker],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # 取消其他任务
                for task in pending:
                    task.cancel()
                    
                # 发送剩余的缓冲区数据
                await self.send_buffer(websocket)
                    
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
                    pcm_data = opus_to_wav(message)
                    if pcm_data:
                        self.last_message_time = asyncio.get_event_loop().time()
                        self.pcm_buffer.extend(pcm_data)
                        
                        # 当缓冲区达到一定大小时发送
                        if len(self.pcm_buffer) >= 1920:  # 60ms的数据
                            await self.send_buffer(client_ws)
                    else:
                        print("音频解码失败，尝试直接转发原始数据")
                        await client_ws.send(message)
        except Exception as e:
            print(f"Server message handling error: {e}")
            # 确保发送剩余的缓冲区数据
            await self.send_buffer(client_ws)

    async def handle_client_messages(self, client_ws, server_ws):
        """处理来自客户端的消息"""
        try:
            async for message in client_ws:
                if isinstance(message, str):
                    print(f"Client text message: {message}")
                else:
                    print("Client binary message (audio)")
                # 直接转发所有消息
                await server_ws.send(message)
        except Exception as e:
            print(f"Client message handling error: {e}")

async def main():
    proxy = WebSocketProxy()
    print(f"Starting proxy server...")
    print(f"Device ID: {proxy.device_id}")
    print(f"Token: {TOKEN}")
    print(f"Target WS URL: {WS_URL}")
    
    server = await websockets.serve(proxy.proxy_handler, "0.0.0.0", 5002)
    print("Proxy server is listening on ws://0.0.0.0:5002")
    await asyncio.Future()  # 运行forever

if __name__ == "__main__":
    asyncio.run(main()) 