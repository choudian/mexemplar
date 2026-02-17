// Content Script - MAIN World
// 只负责覆盖 fetch/XHR，拦截网络请求
(function() {
  'use strict';

  // console.log('[MAIN] Content script (MAIN world) 已加载');

  let isRecording = false;
  let recordingId = null;

  // 避免重复注入
  if (window.__mexemplar_main_injected__) {
    return;
  }
  window.__mexemplar_main_injected__ = true;

  // ⭐ 读取 CDP 注入的配置
  const injectedConfig = window.MEXEMPLAR_CONFIG;
  if (injectedConfig) {
    console.log('[MAIN] 检测到 CDP 注入的配置:', injectedConfig);

    // ⭐ 注意：MAIN world 中不能直接调用 chrome.runtime API
    // 需要通过 postMessage 发送到 ISOLATED world，由其转发
    // 但配置信息已经在 window.MEXEMPLAR_CONFIG 中，Background 可以直接读取

    // ⭐ 保存配置到全局变量，供后续使用
    window.__mexemplar_config = injectedConfig;
  } else {
    console.warn('[MAIN] 未检测到 CDP 注入的配置，使用默认配置');
    // 使用默认值
    window.__mexemplar_config = {
      maxResponseBodySize: 5 * 1024 * 1024  // 默认 5 MB
    };
  }

  // ⭐ 立即从 chrome.storage 读取录制状态（同步初始值）
  // 注意：在 MAIN world 中无法直接访问 chrome.storage，
  // 所以我们通过 ISOLATED world 的帮助来获取
  let initialRecordingStateLoaded = false;

  // ⭐ 立即覆盖 fetch/XHR（在页面脚本之前）
  // 使用 Object.defineProperty 确保覆盖不可被删除
  if (!window.__mexemplar_original_fetch__) {
    window.__mexemplar_original_fetch__ = window.fetch;

    Object.defineProperty(window, 'fetch', {
      configurable: false,
      enumerable: true,
      get: function() {
        return window.__mexemplar_fetch_interceptor__;
      },
      set: function(value) {
        window.__mexemplar_original_fetch__ = value;
      }
    });
  }

  // 覆盖 fetch（增强版）
  window.__mexemplar_fetch_interceptor__ = function(...args) {
    const url = args[0];

    // ⭐ 调试：记录所有 fetch 调用
    if (url && typeof url === 'string') {
      console.log('[MAIN] 🔍 Fetch 被调用:', {
        isRecording: isRecording,
        url: url.substring(0, 100),
        recordingId: recordingId
      });
    }

    if (isRecording && url && typeof url === 'string') {
      console.log('[MAIN] 🌐 Fetch 拦截（正在录制）:', url);
      const startTime = Date.now();

      return window.__mexemplar_original_fetch__.apply(this, args).then(async (response) => {
        try {
          const clonedResponse = response.clone();
          let responseBody = null;

          try {
            const fullText = await clonedResponse.text();
            // ⭐ 从配置读取响应体大小限制（避免 WebSocket 消息过大）
            const MAX_BODY_SIZE = window.__mexemplar_config?.maxResponseBodySize || (5 * 1024 * 1024); // 默认 5 MB
            console.log(`[MAIN] 📄 响应体长度: ${fullText.length} 字符, Content-Type: ${response.headers.get('content-type') || 'unknown'}`);

            if (fullText && fullText.length > MAX_BODY_SIZE) {
              console.warn(`[MAIN] 响应体过大 (${fullText.length} 字节)，截断为 ${MAX_BODY_SIZE} 字节`);
              responseBody = fullText.substring(0, MAX_BODY_SIZE) + '\n\n... [截断：响应体过大] ...';
            } else {
              responseBody = fullText;
            }
            console.log(`[MAIN] ✅ 响应体读取成功, 长度: ${responseBody?.length || 0}`);
          } catch (e) {
            console.warn('[MAIN] ❌ 无法读取响应体:', e.message);
          }

          const networkRequest = {
            url: url,
            method: (args[1] && args[1].method) || 'GET',
            request_type: 'xmlhttprequest',  // ⭐ 新增：标记请求类型
            timestamp: startTime / 1000.0,
            duration: (Date.now() - startTime) / 1000.0,
            request_headers: (args[1] && args[1].headers) || {},
            request_body: (args[1] && args[1].body) || null,
            response_status: response.status,
            response_headers: {},
            response_body: responseBody
          };

          console.log('[MAIN] 📤 准备发送网络请求到 ISOLATED world:', {
            url: url.substring(0, 80),
            hasBody: !!responseBody,
            bodyLength: responseBody?.length || 0
          });

          // 通过 postMessage 发送到 ISOLATED world
          window.postMessage({
            type: 'MEXEMPLAR_NETWORK_REQUEST',
            recording_id: recordingId,
            request: networkRequest
          }, '*');

        } catch (e) {
          console.error('[MAIN] ❌ Fetch 请求捕获失败:', e);
        }

        return response;
      });
    }

    // console.log('[MAIN] Fetch 被调用但不在录制状态，直接透传');
    return window.__mexemplar_original_fetch__.apply(this, args);
  };

  // ⭐ 确保初始值设置正确
  window.__mexemplar_fetch_interceptor__ = window.fetch;

  // 覆盖 XMLHttpRequest
  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function(method, url, ...args) {
    this._mexemplar_method = method;
    this._mexemplar_url = url;
    this._mexemplar_startTime = Date.now();
    return originalOpen.apply(this, [method, url, ...args]);
  };

  XMLHttpRequest.prototype.send = function(body) {
    if (isRecording && this._mexemplar_url) {
      // console.log('[MAIN] 🌐 XHR 拦截:', this._mexemplar_method, this._mexemplar_url);

      this.addEventListener('load', function() {
        try {
          let responseBody = null;
          try {
            const fullText = this.responseText;
            // ⭐ 从配置读取响应体大小限制（避免 WebSocket 消息过大）
            const MAX_BODY_SIZE = window.__mexemplar_config?.maxResponseBodySize || (5 * 1024 * 1024); // 默认 5 MB
            if (fullText && fullText.length > MAX_BODY_SIZE) {
              console.warn(`[MAIN] XHR 响应体过大 (${fullText.length} 字节)，截断为 ${MAX_BODY_SIZE} 字节`);
              responseBody = fullText.substring(0, MAX_BODY_SIZE) + '\n\n... [截断：响应体过大] ...';
            } else {
              responseBody = fullText;
            }
          } catch (e) {
            console.warn('[MAIN] 无法读取 XHR 响应体:', e.message);
          }

          const networkRequest = {
            url: this._mexemplar_url,
            method: this._mexemplar_method || 'GET',
            request_type: 'xmlhttprequest',  // ⭐ 新增：标记请求类型
            timestamp: this._mexemplar_startTime / 1000.0,
            duration: (Date.now() - this._mexemplar_startTime) / 1000.0,
            request_body: body,
            response_status: this.status,
            response_headers: {},
            response_body: responseBody
          };

          // console.log('[MAIN] 📤 发送 XHR 请求到 ISOLATED world, 有响应体:', !!responseBody);

          // 通过 postMessage 发送到 ISOLATED world
          window.postMessage({
            type: 'MEXEMPLAR_NETWORK_REQUEST',
            recording_id: recordingId,
            request: networkRequest
          }, '*');

        } catch (e) {
          console.error('[MAIN] XHR 请求捕获失败:', e);
        }
      });
    }

    return originalSend.apply(this, [body]);
  };

  // console.log('[MAIN] ✅ Fetch 和 XHR 已覆盖');

  // 监听来自 ISOLATED world 的消息（设置录制状态）
  window.addEventListener('message', (event) => {
    if (event.data.type === 'MEXEMPLAR_SET_RECORDING') {
      console.log('[MAIN] ✅ 收到录制状态设置:', event.data);
      isRecording = event.data.isRecording;
      recordingId = event.data.recordingId;
      console.log('[MAIN] 🎯 isRecording 已设置为:', isRecording, 'recordingId:', recordingId);
    }
  });

  // ⭐ 主动请求录制状态（处理动态注入的情况）
  // 通过 postMessage 通知 ISOLATED world，请求当前录制状态
  window.postMessage({
    type: 'MEXEMPLAR_REQUEST_RECORDING_STATUS'
  }, '*');

  console.log('[MAIN] ✅ Content script (MAIN world) 初始化完成，isRecording =', isRecording);
})();
