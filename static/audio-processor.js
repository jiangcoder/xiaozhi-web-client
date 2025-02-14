class AudioProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super();
        this.bufferSize = options.processorOptions.bufferSize;
        this.buffer = new Float32Array();
        this.sampleRate = 16000;
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
                const sample = Math.max(-1, Math.min(1, chunk[i]));
                pcmData[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
            }

            // 发送数据到主线程
            this.port.postMessage(pcmData, [pcmData.buffer]);
        }

        return true;
    }
}

registerProcessor('audio-processor', AudioProcessor);