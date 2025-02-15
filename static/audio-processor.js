class AudioProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super();
        this.bufferSize = options.processorOptions.bufferSize;
        this.buffer = new Float32Array();
        this.sampleRate = 16000;
        this.waitingForLastData = false;
        
        // 添加消息处理
        this.port.onmessage = (e) => {
            if (e.data.type === 'reset') {
                this.resetBuffer();
            } else if (e.data.type === 'getLastData') {
                this.waitingForLastData = true;
            }
        };
    }

    resetBuffer() {
        this.buffer = new Float32Array();
        this.waitingForLastData = false;
    }

    process(inputs, outputs) {
        const input = inputs[0][0];
        if (!input) return true;

        // 将新数据添加到缓冲区
        const newBuffer = new Float32Array(this.buffer.length + input.length);
        newBuffer.set(this.buffer);
        newBuffer.set(input, this.buffer.length);
        this.buffer = newBuffer;

        // 当缓冲区达到指定大小时处理数据
        while (this.buffer.length >= this.bufferSize) {
            // 提取数据
            const chunk = this.buffer.slice(0, this.bufferSize);
            this.buffer = this.buffer.slice(this.bufferSize);

            // 转换为16位整数
            const pcmData = new Int16Array(this.bufferSize);
            for (let i = 0; i < chunk.length; i++) {
                // 确保音频数据在[-1,1]范围内
                const sample = Math.max(-1, Math.min(1, chunk[i]));
                // 转换为16位整数 (-32768 到 32767)
                pcmData[i] = Math.round(sample * 32767);
            }

            // 发送数据到主线程
            this.port.postMessage(pcmData, [pcmData.buffer]);
        }

        // 如果正在等待最后的数据，并且缓冲区中还有数据，处理它们
        if (this.waitingForLastData && this.buffer.length > 0) {
            const pcmData = new Int16Array(this.buffer.length);
            for (let i = 0; i < this.buffer.length; i++) {
                const sample = Math.max(-1, Math.min(1, this.buffer[i]));
                pcmData[i] = Math.round(sample * 32767);
            }
            this.port.postMessage(pcmData, [pcmData.buffer]);
            this.buffer = new Float32Array();
            
            // 发送最后数据处理完成的消息
            this.port.postMessage({ type: 'lastData' });
            this.waitingForLastData = false;
        }

        return true;
    }
}

registerProcessor('audio-processor', AudioProcessor);