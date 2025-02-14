class AudioProcessor extends AudioWorkletProcessor {
    constructor(options) {
        super();
        this.bufferSize = options.processorOptions.bufferSize;
        this.sampleRate = 16000;

        // 初始化处理状态
        this.state = {
            preEmphasis: 0.97,
            preEmphasisState: 0,
            agcState: {
                gainDb: 0,
                targetLevelDbfs: 3,
                compressionGainDb: 9,
                limiterEnabled: true
            },
            nsState: {
                smoothedPsd: new Float32Array(256),
                noisePsd: new Float32Array(256),
                priorSnr: new Float32Array(256),
                smoothingAlpha: 0.98
            },
            vadState: {
                energyThreshold: 0.1,
                zcr: 0,
                lastVadResult: false,
                smoothedVad: 0,
                hangoverFrames: 0,
                maxHangover: 10
            }
        };

        // FFT设置
        this.fftSize = 512;
        this.hannWindow = this.createHannWindow(this.fftSize);
        
        // 初始化缓冲区
        this.buffer = {
            input: new Float32Array(960),
            processed: new Float32Array(480),
            position: 0
        };

        this.port.onmessage = (e) => {
            if (e.data.type === 'reset') {
                this.reset();
            } else if (e.data.type === 'setConfig') {
                this.updateConfig(e.data.config);
            }
        };
    }

    // 创建Hann窗
    createHannWindow(size) {
        const window = new Float32Array(size);
        for (let i = 0; i < size; i++) {
            window[i] = 0.5 * (1 - Math.cos((2 * Math.PI * i) / (size - 1)));
        }
        return window;
    }

    // 重置处理状态
    reset() {
        this.state.preEmphasisState = 0;
        this.state.agcState.gainDb = 0;
        this.state.nsState.smoothedPsd.fill(0);
        this.state.nsState.noisePsd.fill(0);
        this.state.nsState.priorSnr.fill(0);
        this.state.vadState.zcr = 0;
        this.state.vadState.lastVadResult = false;
        this.state.vadState.smoothedVad = 0;
        this.state.vadState.hangoverFrames = 0;
        this.buffer.position = 0;
        this.buffer.input.fill(0);
        this.buffer.processed.fill(0);
    }

    // 前置加重
    preEmphasis(frame) {
        const output = new Float32Array(frame.length);
        for (let i = 0; i < frame.length; i++) {
            output[i] = frame[i] - this.state.preEmphasis * this.state.preEmphasisState;
            this.state.preEmphasisState = frame[i];
        }
        return output;
    }

    // 自动增益控制
    processAGC(frame) {
        // 计算RMS能量
        let rms = 0;
        for (let i = 0; i < frame.length; i++) {
            rms += frame[i] * frame[i];
        }
        rms = Math.sqrt(rms / frame.length);
        
        // 计算dB级别
        const levelDb = 20 * Math.log10(Math.max(rms, 1e-9));
        const gainError = this.state.agcState.targetLevelDbfs - levelDb;
        
        // 更新增益
        let newGainDb = this.state.agcState.gainDb + 0.2 * gainError;
        
        // 限幅
        if (this.state.agcState.limiterEnabled) {
            newGainDb = Math.min(newGainDb, this.state.agcState.compressionGainDb);
        }
        
        // 应用增益
        const gain = Math.pow(10, newGainDb / 20);
        const output = new Float32Array(frame.length);
        for (let i = 0; i < frame.length; i++) {
            output[i] = frame[i] * gain;
        }
        
        this.state.agcState.gainDb = newGainDb;
        return output;
    }

    // 噪声抑制
    processNS(frame) {
        // 应用窗函数
        const windowed = new Float32Array(this.fftSize);
        for (let i = 0; i < frame.length; i++) {
            windowed[i] = frame[i] * this.hannWindow[i];
        }
        
        // 执行FFT
        const fft = new Float32Array(this.fftSize);
        this.fft(windowed, fft);
        
        // 计算功率谱
        const psd = new Float32Array(this.fftSize / 2 + 1);
        for (let i = 0; i <= this.fftSize / 2; i++) {
            psd[i] = fft[2 * i] * fft[2 * i] + fft[2 * i + 1] * fft[2 * i + 1];
        }
        
        // 更新平滑PSD和噪声PSD
        for (let i = 0; i <= this.fftSize / 2; i++) {
            this.state.nsState.smoothedPsd[i] = this.state.nsState.smoothingAlpha * this.state.nsState.smoothedPsd[i] +
                                              (1 - this.state.nsState.smoothingAlpha) * psd[i];
            
            // 使用最小统计法更新噪声PSD
            if (psd[i] < this.state.nsState.noisePsd[i]) {
                this.state.nsState.noisePsd[i] = 0.8 * this.state.nsState.noisePsd[i] + 0.2 * psd[i];
            } else {
                this.state.nsState.noisePsd[i] = 0.998 * this.state.nsState.noisePsd[i];
            }
            
            // 计算先验信噪比
            const snrPrior = Math.max(
                this.state.nsState.smoothedPsd[i] / Math.max(this.state.nsState.noisePsd[i], 1e-9) - 1,
                0
            );
            this.state.nsState.priorSnr[i] = Math.max(snrPrior, 0.1);
        }
        
        // 维纳滤波
        for (let i = 0; i <= this.fftSize / 2; i++) {
            const gain = this.state.nsState.priorSnr[i] / (1 + this.state.nsState.priorSnr[i]);
            fft[2 * i] *= gain;
            fft[2 * i + 1] *= gain;
        }
        
        // 执行IFFT
        const output = new Float32Array(frame.length);
        this.ifft(fft, output);
        
        // 应用窗函数并归一化
        for (let i = 0; i < frame.length; i++) {
            output[i] *= this.hannWindow[i] / (this.fftSize / 4);
        }
        
        return output;
    }

    // VAD检测
    processVAD(frame) {
        // 计算短时能量
        let energy = 0;
        for (let i = 0; i < frame.length; i++) {
            energy += frame[i] * frame[i];
        }
        energy /= frame.length;
        
        // 计算过零率
        let zcr = 0;
        for (let i = 1; i < frame.length; i++) {
            if ((frame[i] >= 0 && frame[i - 1] < 0) || 
                (frame[i] < 0 && frame[i - 1] >= 0)) {
                zcr++;
            }
        }
        zcr /= frame.length;
        
        // 更新VAD状态
        const energyThreshold = this.state.vadState.energyThreshold;
        const zcrThreshold = 0.2;
        
        let vadResult = (energy > energyThreshold) && (zcr > zcrThreshold);
        
        // 平滑处理
        this.state.vadState.smoothedVad = 0.7 * this.state.vadState.smoothedVad +
                                        0.3 * (vadResult ? 1 : 0);
        
        // Hangover处理
        if (this.state.vadState.smoothedVad > 0.5) {
            this.state.vadState.hangoverFrames = this.state.vadState.maxHangover;
            vadResult = true;
        } else if (this.state.vadState.hangoverFrames > 0) {
            this.state.vadState.hangoverFrames--;
            vadResult = true;
        } else {
            vadResult = false;
        }
        
        this.state.vadState.lastVadResult = vadResult;
        return vadResult;
    }

    // FFT实现
    fft(input, output) {
        // 使用Web Audio API的FFT实现
        // 这里使用简化版本，实际应使用完整的FFT库
        for (let i = 0; i < input.length; i++) {
            output[i] = input[i];
        }
    }

    // IFFT实现
    ifft(input, output) {
        // 使用Web Audio API的IFFT实现
        // 这里使用简化版本，实际应使用完整的FFT库
        for (let i = 0; i < input.length; i++) {
            output[i] = input[i];
        }
    }

    process(inputs, outputs) {
        const input = inputs[0][0];
        if (!input) return true;

        // 1. 前置加重
        let processedFrame = this.preEmphasis(input);
        
        // 2. 噪声抑制
        processedFrame = this.processNS(processedFrame);
        
        // 3. VAD检测
        const isVoice = this.processVAD(processedFrame);
        
        // 4. AGC处理
        if (isVoice) {
            processedFrame = this.processAGC(processedFrame);
        }

        // 转换为PCM
        const pcmData = new Int16Array(processedFrame.length);
        for (let i = 0; i < processedFrame.length; i++) {
            const sample = Math.max(-1, Math.min(1, processedFrame[i]));
            pcmData[i] = Math.round(sample * 32767);
        }

        // 发送处理后的数据
        this.port.postMessage(pcmData, [pcmData.buffer]);

        return true;
    }
}

// 注册 AudioWorklet 处理器
registerProcessor('audio-processor', AudioProcessor);