# 小智AI Web客户端实现

如果想体验小智项目，或者开发server端测试的同志，可以使用这个web端damo 体验下。
由于是当天开发当天上传的，语音端还没有做好，只实现了文字端的，可以语音加文字输出。
等迭代慢慢完善。

## 功能特点

- 实时语音对话
- 文本消息支持
- 自动重连机制
- 流式音频播放
- 设备认证支持 WS token 同步了主仓库的server端，只认证mac

## 安装

1. 克隆仓库：

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 配置环境变量：
创建 `.env` 文件并设置以下参数：
```
DEVICE_TOKEN=your_token
WS_URL=ws://your_server_address:9005
```

## 运行 双开终端 或者 docker 

1. 启动代理服务器：
```bash
python proxy.py
```

2. 启动Web服务器：
```bash
python app.py
```

3. 访问：
打开浏览器访问 `http://localhost:5001`

## 使用说明

1. 打开网页后，系统会自动连接到WebSocket服务器
2. 可以通过以下方式与小智对话：
   - 点击"录音"按钮进行语音输入（最长5秒） //待迭代
   - 在文本框输入文字后按回车或点击发送

## 配置说明

- `proxy.py`: WebSocket代理服务器，处理音频转换和数据转发
- `app.py`: Web服务器，提供Web界面
- `templates/index.html`: 前端界面
- `.env`: 环境配置文件

### 环境变量

- `DEVICE_TOKEN`: 设备认证令牌 //随便填吧
- `WS_URL`: WebSocket服务器地址

