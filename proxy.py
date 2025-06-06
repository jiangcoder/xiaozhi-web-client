import asyncio
import websockets
import os
import json
from dotenv import load_dotenv
import uuid
import time  # 添加这一行
import wave
import io
import numpy as np
from urllib.parse import urlparse
from system_info import setup_opus
import sys

# 在导入 opuslib 之前处理 opus 动态库
setup_opus()
try:
    import opuslib
except Exception as e:
    print(f"导入 opuslib 失败: {e}")
    print("请确保 opus 动态库已正确安装或位于正确的位置")
    sys.exit(1)

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

LOCAL_PROXY_URL = os.getenv("LOCAL_PROXY_URL", "ws://localhost:5002")
try:
    # 从LOCAL_PROXY_URL中提取主机和端口
    parsed_url = urlparse(LOCAL_PROXY_URL)
    PROXY_HOST = '0.0.0.0'  # 总是监听在所有网络接口上
    PROXY_PORT = parsed_url.port or 5002
except Exception as e:
    print(f"解析LOCAL_PROXY_URL失败: {e}，使用默认值")
    PROXY_HOST = '0.0.0.0'
    PROXY_PORT = 5002


def get_mac_address():
    mac = uuid.getnode()
    return ':'.join(['{:02x}'.format((mac >> elements) & 0xff) for elements in range(0, 8 * 6, 8)][::-1])


CLIENT_ID = os.getenv("CLIENT_ID", "")


def get_client_id():
    if not CLIENT_ID:
        new_client_id = str(uuid.uuid4())
        with open(".env", "a") as env_file:
            env_file.write(f"CLIENT_ID={new_client_id}\n")
        os.environ["CLIENT_ID"] = new_client_id
        return new_client_id
    return CLIENT_ID



class AudioProcessor:
    def __init__(self, buffer_size=480):
        self.buffer_size = buffer_size
        self.buffer = np.array([], dtype=np.float32)
        self.sample_rate = 8000

    def reset_buffer(self):
        self.buffer = np.array([], dtype=np.float32)

    def process_audio(self, input_data):
        # 将输入数据转换为float32数组
        input_array = np.frombuffer(input_data, dtype=np.float32)

        # 将新数据添加到缓冲区
        self.buffer = np.append(self.buffer, input_array)

        chunks = []
        # 当缓冲区达到指定大小时处理数据
        while len(self.buffer) >= self.buffer_size:
            # 提取数据
            chunk = self.buffer[:self.buffer_size]
            self.buffer = self.buffer[self.buffer_size:]

            # 转换为16位整数
            pcm_data = (chunk * 32767).astype(np.int16)
            chunks.append(pcm_data.tobytes())

        return chunks

    def process_remaining(self):
        if len(self.buffer) > 0:
            # 转换为16位整数
            pcm_data = (self.buffer * 32767).astype(np.int16)
            self.buffer = np.array([], dtype=np.float32)
            return [pcm_data.tobytes()]
        return []


class WebSocketProxy:
    def __init__(self):
        self.device_id = get_mac_address()
        self.client_id = get_client_id()
        self.enable_token = os.getenv("ENABLE_TOKEN", "true").lower() == "true"
        self.token = os.getenv("DEVICE_TOKEN", "123")

        # 根据 token 开关设置 headers
        self.headers = {
            "Device-Id": self.device_id,
            "Client-Id": self.client_id,
            "Protocol-Version": "1",
        }
        if self.enable_token:
            self.headers["Authorization"] = f"Bearer {self.token}"

        self.audio_processor = AudioProcessor(buffer_size=480)
        self.decoder = opuslib.Decoder(8000, 1)  # 创建一个持久的解码器实例
        self.audio_buffer = bytearray()  # 改用 bytearray 存储音频数据
        self.is_first_audio = True
        self.total_samples = 0  # 跟踪总采样数

    def create_wav_header(self, total_samples):
        """创建WAV文件头"""
        header = bytearray(44)  # WAV header is 44 bytes
    
        # RIFF header
        header[0:4] = b'RIFF'
        header[4:8] = (total_samples * 2 + 36).to_bytes(4, 'little')  # File size
        header[8:12] = b'WAVE'
    
        # fmt chunk
        header[12:16] = b'fmt '
        header[16:20] = (16).to_bytes(4, 'little')  # Chunk size
        header[20:22] = (1).to_bytes(2, 'little')  # Audio format (PCM)
        header[22:24] = (1).to_bytes(2, 'little')  # Num channels
        header[24:28] = (8000).to_bytes(4, 'little')  # Sample rate 修改为8000
        header[28:32] = (16000).to_bytes(4, 'little')  # Byte rate 修改为8000*2=16000
        header[32:34] = (2).to_bytes(2, 'little')  # Block align
        header[34:36] = (16).to_bytes(2, 'little')  # Bits per sample
    
        # data chunk
        header[36:40] = b'data'
        header[40:44] = (total_samples * 2).to_bytes(4, 'little')  # Data size
    
        return header

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
            # 创建音频保存目录
            audio_dir = os.path.join(os.path.dirname(__file__), "audio_files")
            os.makedirs(audio_dir, exist_ok=True)
            
            # 为每个会话创建唯一的文件名
            session_timestamp = int(time.time())
            audio_file_path = os.path.join(audio_dir, f"audio_{session_timestamp}.pcm")
            audio_file = None
            
            # PCM 数据缓冲区
            pcm_buffer = bytearray()
            
            async for message in server_ws:
                if isinstance(message, str):
                    try:
                        msg_data = json.loads(message)
                        if msg_data.get('type') == 'tts' and msg_data.get('state') == 'start':
                            # 新的音频流开始，重置状态
                            print("处理服务器音频数据-新的音频流开始，重置状态")
                            
                            # 如果还有未播放的数据，先发送
                            if len(pcm_buffer) > 0:
                                # 添加WAV头后发送
                                wav_data = self.create_wav_header(len(pcm_buffer) // 2)
                                wav_data.extend(pcm_buffer)
                                await client_ws.send(bytes(wav_data))
                                
                                # 保存之前的音频数据到文件
                                if audio_file:
                                    audio_file.close()
                                
                                # 为新的音频流创建新的文件
                                audio_file_path = os.path.join(audio_dir, f"audio_{int(time.time())}.pcm")
                                audio_file = open(audio_file_path, "wb")
                                audio_file.write(bytes(pcm_buffer))
                                print(f"音频数据已保存到: {audio_file_path}")

                            # 完全重置状态
                            pcm_buffer = bytearray()
                            self.total_samples = 0

                        elif msg_data.get('type') == 'tts' and msg_data.get('state') == 'stop':
                            # 音频流结束，发送剩余数据
                            print("处理服务器音频数据-音频流结束，发送剩余数据")
                            if len(pcm_buffer) > 0:
                                # 添加WAV头后发送
                                wav_data = self.create_wav_header(len(pcm_buffer) // 2)
                                wav_data.extend(pcm_buffer)
                                await client_ws.send(bytes(wav_data))
                                
                                # 保存最终的音频数据到文件
                                if audio_file:
                                    audio_file.write(bytes(pcm_buffer))
                                    audio_file.close()
                                    print(f"音频数据已完成保存到: {audio_file_path}")
                                    audio_file = None

                                # 等待一小段时间确保音频播放完成
                                await asyncio.sleep(0.1)

                                # 完全重置状态
                                pcm_buffer = bytearray()
                                self.total_samples = 0

                        await client_ws.send(message)
                    except json.JSONDecodeError:
                        await client_ws.send(message)
                else:
                    try:
                        # 直接处理PCM数据
                        print("处理服务器音频数据-pcm")
                        pcm_data = message  # 直接使用PCM数据
                        if pcm_data:
                            # 计算采样数
                            samples = len(pcm_data) // 2  # 16位音频，每个采样2字节
                            self.total_samples += samples

                            # 如果文件还没有打开，则打开文件
                            if audio_file is None:
                                audio_file_path = os.path.join(audio_dir, f"audio_{int(time.time())}.pcm")
                                try:
                                    audio_file = open(audio_file_path, "wb")
                                    print(f"创建新的音频文件: {audio_file_path}")
                                except Exception as e:
                                    print(f"创建音频文件失败: {e}")

                            # 直接添加PCM数据到缓冲区，不添加WAV头
                            pcm_buffer.extend(pcm_data)
                            
                            # 将新的音频数据追加到文件
                            if audio_file:
                                try:
                                    audio_file.write(pcm_data)
                                    audio_file.flush()  # 确保数据立即写入磁盘
                                except Exception as e:
                                    print(f"写入音频文件失败: {e}")

                            # 当缓冲区达到一定大小时发送数据
                            if len(pcm_buffer) >= 16000:  # 约1秒的音频数据
                                # 添加WAV头后发送
                                wav_data = self.create_wav_header(len(pcm_buffer) // 2)
                                wav_data.extend(pcm_buffer)
                                await client_ws.send(bytes(wav_data))
                                
                                # 重置PCM缓冲区
                                pcm_buffer = bytearray()
                    except Exception as e:
                        print(f"音频处理错误: {e}")
                        
            # 确保文件被关闭
            if audio_file:
                audio_file.close()
                print(f"音频文件已关闭: {audio_file_path}")
            
        except Exception as e:
            print(f"Server message handling error: {e}")
            # 确保文件被关闭
            if 'audio_file' in locals() and audio_file:
                audio_file.close()

    async def handle_client_messages(self, client_ws, server_ws):
        """处理来自客户端的消息"""
        try:
            async for message in client_ws:
                if isinstance(message, str):
                    try:
                        msg_data = json.loads(message)
                        if msg_data.get('type') == 'reset':
                            self.audio_processor.reset_buffer()
                        elif msg_data.get('type') == 'getLastData':
                            # 处理剩余数据
                            remaining_chunks = self.audio_processor.process_remaining()
                            for chunk in remaining_chunks:
                                await server_ws.send(chunk)
                            # 发送处理完成消息
                            await client_ws.send(json.dumps({'type': 'lastData'}))
                        else:
                            await server_ws.send(message)
                    except json.JSONDecodeError:
                        await server_ws.send(message)
                else:
                    try:
                        audio_data = np.frombuffer(message, dtype=np.float32)
                        if len(audio_data) > 0:
                            # 使用AudioProcessor处理音频数据
                            chunks = self.audio_processor.process_audio(audio_data.tobytes())
                            for chunk in chunks:
                                # 直接发送PCM数据，不再转换为Opus
                                await server_ws.send(chunk)
                        else:
                            print("收到空的音频数据")
                    except Exception as e:
                        print(f"音频处理错误: {e}")
        except Exception as e:
            print(f"Client message handling error: {e}")

    async def main(self):
        """启动代理服务器"""
        print(f"Starting proxy server on {PROXY_HOST}:{PROXY_PORT}")
        print(f"Device ID: {self.device_id}")
        print(f"Token: {TOKEN}")
        print(f"Target WS URL: {WS_URL}")

        async with websockets.serve(self.proxy_handler, PROXY_HOST, PROXY_PORT):
            await asyncio.Future()  # 运行直到被取消


if __name__ == "__main__":
    proxy = WebSocketProxy()
    asyncio.run(proxy.main())