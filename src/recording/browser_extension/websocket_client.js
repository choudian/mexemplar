/**
 * WebSocket 客户端 - 用于与 Python 服务器通信
 *
 * 替代 Native Messaging，提供实时事件传输
 */

class WebSocketClient {
    constructor(url = 'ws://localhost:8765') {
        this.url = url;
        this.ws = null;
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;  // 初始重连延迟（毫秒）
        this.messageQueue = [];  // 离线消息队列
        this.heartbeatInterval = null;
        this.isRecording = false;
        this.recordingId = null;  // 保存当前录制 ID

        // 消息回调（用于 background.js）
        this.onControlStart = null;
        this.onControlStop = null;

        // 绑定方法
        this.connect = this.connect.bind(this);
        this.handleOpen = this.handleOpen.bind(this);
        this.handleMessage = this.handleMessage.bind(this);
        this.handleClose = this.handleClose.bind(this);
        this.handleError = this.handleError.bind(this);
    }

    /**
     * 连接到 WebSocket 服务器
     */
    connect() {
        console.log(`[WebSocket] Connecting to ${this.url}...`);

        try {
            this.ws = new WebSocket(this.url);

            this.ws.onopen = this.handleOpen;
            this.ws.onmessage = this.handleMessage;
            this.ws.onclose = this.handleClose;
            this.ws.onerror = this.handleError;

        } catch (error) {
            console.error('[WebSocket] Connection failed:', error);
            this.scheduleReconnect();
        }
    }

    /**
     * 处理连接打开事件
     */
    handleOpen() {
        console.log('[WebSocket] Connected successfully');
        this.connected = true;
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;

        // 发送离线消息队列
        this.flushMessageQueue();

        // 启动心跳
        this.startHeartbeat();

        // 通知连接成功
        this.notifyConnectionStatus(true);
    }

    /**
     * 处理接收到的消息
     */
    handleMessage(event) {
        try {
            const message = JSON.parse(event.data);

            switch (message.type) {
                case 'control_start':
                    console.log(`[WebSocket] Start recording command: ${message.recording_id}`);
                    this.handleStartRecording(message);
                    break;

                case 'control_stop':
                    this.handleStopRecording(message);
                    break;

                case 'ping':
                    // 回复 PONG
                    this.send({
                        type: 'pong',
                        timestamp: Date.now() / 1000.0
                    });
                    break;

                case 'pong':
                    console.log('[WebSocket] Heartbeat pong received');
                    break;

                case 'config_change':
                    // ⭐ 处理配置变化通知
                    console.log('[WebSocket] 配置变化通知:', message);
                    this.handleConfigChange(message);
                    break;

                default:
                    console.log('[WebSocket] Unknown message type:', message.type);
            }

        } catch (error) {
            console.error('[WebSocket] Failed to parse message:', error);
        }
    }

    /**
     * 处理连接关闭事件
     */
    handleClose() {
        console.log('[WebSocket] Connection closed');
        this.connected = false;

        // 停止心跳
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }

        // 通知连接断开
        this.notifyConnectionStatus(false);

        // 如果正在录制，尝试重连
        if (this.isRecording) {
            this.scheduleReconnect();
        }
    }

    /**
     * 处理错误事件
     */
    handleError(error) {
        console.error('[WebSocket] Error:', error);
    }

    /**
     * 发送消息
     */
    send(message) {
        if (this.connected && this.ws.readyState === WebSocket.OPEN) {
            try {
                this.ws.send(JSON.stringify(message));
                return true;
            } catch (error) {
                console.error('[WebSocket] Send failed:', error);
                return false;
            }
        } else {
            // 离线时缓存消息（最多 1000 条）
            this.messageQueue.push(message);

            if (this.messageQueue.length > 1000) {
                this.messageQueue.shift();
            }

            console.log(`[WebSocket] Offline, queued message (${this.messageQueue.length}/1000)`);
            return false;
        }
    }

    /**
     * 发送浏览器动作
     */
    sendAction(action) {
        const message = {
            type: 'browser_action',
            recording_id: this.recordingId || null,  // 使用实例变量
            action: action,
            timestamp: Date.now() / 1000.0
        };

        return this.send(message);
    }

    /**
     * 处理开始录制命令
     */
    handleStartRecording(message) {
        const recordingId = message.recording_id;

        console.log(`[WebSocket] Starting recording: ${recordingId}`);

        // 保存录制 ID 到实例变量
        this.recordingId = recordingId;
        this.isRecording = true;

        // 调用回调函数（如果设置）
        if (this.onControlStart) {
            this.onControlStart(message);
        } else {
            console.warn('[WebSocket] ⚠️ onControlStart 回调未设置！');
        }

    }

    /**
     * 处理停止录制命令
     */
    handleStopRecording(message) {

        this.isRecording = false;

        // 调用回调函数（如果设置）
        if (this.onControlStop) {
            this.onControlStop(message);
        }

    }

    /**
     * ⭐ 处理配置变化通知
     * 当 Python 端修改 WebSocket 配置时触发
     */
    handleConfigChange(message) {
        const newUrl = message.new_websocket_url;

        console.log(`[WebSocket] 配置变化: ${this.url} -> ${newUrl}`);

        // 关闭旧连接
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            console.log('[WebSocket] 关闭旧连接...');
            this.ws.close();
        }

        // 更新 URL
        this.url = newUrl;

        // 延迟 1 秒后重连（给 Python 端时间重启服务器）
        console.log('[WebSocket] 1 秒后重连到新地址...');
        setTimeout(() => {
            console.log(`[WebSocket] 重连到 ${this.url}`);
            this.connect();
        }, 1000);
    }

    /**
     * 启动心跳（每 30 秒发送 PING）
     */
    startHeartbeat() {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
        }

        this.heartbeatInterval = setInterval(() => {
            if (this.connected) {
                this.send({
                    type: 'ping',
                    timestamp: Date.now() / 1000.0
                });
            }
        }, 30000);  // 30 秒
    }

    /**
     * 安排重连（指数退避）
     */
    scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('[WebSocket] Max reconnect attempts reached');
            return;
        }

        this.reconnectAttempts++;

        // 指数退避：1s, 2s, 4s, 8s, ...
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

        console.log(
            `[WebSocket] Reconnecting in ${delay}ms ` +
            `(${this.reconnectAttempts}/${this.maxReconnectAttempts})`
        );

        setTimeout(() => this.connect(), delay);
    }

    /**
     * 发送离线消息队列
     */
    flushMessageQueue() {
        if (this.messageQueue.length === 0) {
            return;
        }

        console.log(`[WebSocket] Sending ${this.messageQueue.length} queued messages`);

        while (this.messageQueue.length > 0) {
            const message = this.messageQueue.shift();
            this.send(message);
        }
    }

    /**
     * 通知连接状态
     */
    notifyConnectionStatus(connected) {
        // WebSocket 连接状态变化时触发自定义事件
        console.log(`[WebSocket] Connection status: ${connected ? 'connected' : 'disconnected'}`);

        // 注意：Service Worker 中没有 window 对象，跳过事件触发
        if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('mexemplar-websocket-status', {
                detail: { connected: connected }
            }));
        }
    }

    /**
     * 断开连接
     */
    disconnect() {
        console.log('[WebSocket] Disconnecting...');

        // 停止心跳
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }

        // 关闭 WebSocket
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }

        this.connected = false;
        this.isRecording = false;
        this.reconnectAttempts = 0;

        console.log('[WebSocket] Disconnected');
    }
}

