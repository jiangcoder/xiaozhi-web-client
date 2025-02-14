import asyncio
import json
import websockets
import pyaudio
import wave
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# WebSocket配置
WS_URL = "ws://10.1.5.14:9005"
TOKEN = os.getenv("DEVICE_TOKEN", "your-token1")  # 从环境变量获取token，默认使用your-token1

# 音频配置
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
RECORD_SECONDS = 5

class XiaozhiClient:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        
    async def connect(self):
        # 构建认证头
        headers = {
            "Authorization": f"Bearer {TOKEN}",
            "device-id": get_mac_address()  # 添加device-id
        }
        
        async with websockets.connect(WS_URL, extra_headers=headers) as websocket:
            print("Connected to server")
            while True:
                # 录音
                input("Press Enter to start recording...")
                frames = self.record_audio()
                
                # 保存音频
                self.save_audio(frames, "output.wav")
                
                # 发送音频文件
                with open("output.wav", "rb") as f:
                    audio_data = f.read()
                    await websocket.send(audio_data)
                
                # 接收响应
                response = await websocket.recv()
                if isinstance(response, bytes):
                    # 保存返回的音频
                    with open("response.wav", "wb") as f:
                        f.write(response)
                    print("Received audio response")
                    self.play_audio("response.wav")
                else:
                    print(f"Received text: {response}")

    def record_audio(self):
        print("* recording")
        stream = self.p.open(format=FORMAT,
                           channels=CHANNELS,
                           rate=RATE,
                           input=True,
                           frames_per_buffer=CHUNK)

        frames = []
        for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
            data = stream.read(CHUNK)
            frames.append(data)

        print("* done recording")
        stream.stop_stream()
        stream.close()
        return frames

    def save_audio(self, frames, filename):
        wf = wave.open(filename, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(self.p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(frames))
        wf.close()

    def play_audio(self, filename):
        wf = wave.open(filename, 'rb')
        stream = self.p.open(format=self.p.get_format_from_width(wf.getsampwidth()),
                           channels=wf.getnchannels(),
                           rate=wf.getframerate(),
                           output=True)

        data = wf.readframes(CHUNK)
        while data:
            stream.write(data)
            data = wf.readframes(CHUNK)

        stream.stop_stream()
        stream.close()
        wf.close()

    def close(self):
        self.p.terminate()

async def main():
    client = XiaozhiClient()
    try:
        await client.connect()
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        client.close()

if __name__ == "__main__":
    asyncio.run(main()) 