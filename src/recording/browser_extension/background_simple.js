// WebSocket 客户端（替代 Native Messaging）
// 必须在所有其他代码之前 importScripts
importScripts('launch_context.js');
importScripts('websocket_client.js');

// console.log('[BACKGROUND] Service Worker 已启动');

let wsClient = null;
let isRecording = false;
let recordingId = null;
let recordingSource = null;
let hasLoadedPersistedState = false;
const launchContext = self.MEXEMPLAR_LAUNCH_CONTEXT || {};

const RECORDING_SOURCE = Object.freeze({
  PLAYWRIGHT: 'playwright',
  EXTENSION_TRIGGERED: 'extension_triggered',
});

const STORAGE_KEYS = [
  'isRecording',
  'recordingId',
  'recordingSource',
  'extensionTriggeredRecording',
  'extensionTriggeredRecordingId',
];

// ⭐ 新增：网络请求存储（按 origin 分组）
const networkRequests = new Map(); // origin -> []Array

// ⭐ 动态 WebSocket URL（可通过 CDP 注入更新）
let WEBSOCKET_URL = 'ws://localhost:8765';  // 默认值

function isWsConnected() {
  return Boolean(wsClient && wsClient.connected && wsClient.ws && wsClient.ws.readyState === WebSocket.OPEN);
}

function sendControlAction(action, notConnectedError, sendResponse) {
  if (wsClient) wsClient.ensureConnected();
  if (!isWsConnected()) {
    sendResponse({ success: false, error: notConnectedError });
    return;
  }
  const ok = wsClient.send({ type: 'recording_control', action, source: 'extension' });
  sendResponse({ success: ok, pending: ok, error: ok ? null : '发送控制消息失败' });
}

function ensureNetworkRequestsCapacity() {
  if (networkRequests.size > 200) {
    const firstKey = networkRequests.keys().next().value;
    networkRequests.delete(firstKey);
  }
}

function storeNetworkRequest(origin, request) {
  if (!isRecording) return;
  if (!networkRequests.has(origin)) {
    ensureNetworkRequestsCapacity();
    networkRequests.set(origin, []);
  }
  const requests = networkRequests.get(origin);
  requests.push(request);
  if (requests.length > 10) {
    requests.shift();
  }
}

function getCurrentRecordingState() {
  return {
    isRecording: isRecording,
    recordingId: recordingId,
    recordingSource: recordingSource
  };
}

function resolvePersistedRecordingState(state = {}) {
  if (hasLoadedPersistedState || isRecording || recordingId !== null || recordingSource !== null) {
    return getCurrentRecordingState();
  }

  if (state.isRecording) {
    return {
      isRecording: true,
      recordingId: state.recordingId || null,
      recordingSource: state.recordingSource || RECORDING_SOURCE.PLAYWRIGHT
    };
  }

  if (state.extensionTriggeredRecording) {
    return {
      isRecording: true,
      recordingId: state.extensionTriggeredRecordingId || null,
      recordingSource: RECORDING_SOURCE.EXTENSION_TRIGGERED
    };
  }

  return {
    isRecording: false,
    recordingId: null,
    recordingSource: null
  };
}

function setRecordingState(nextIsRecording, nextRecordingId, nextRecordingSource) {
  isRecording = nextIsRecording;
  recordingId = nextRecordingId;
  recordingSource = nextRecordingSource;
  hasLoadedPersistedState = true;
  persistRecordingState();
}

function persistRecordingState() {
  const playwrightRecording = isRecording && recordingSource === RECORDING_SOURCE.PLAYWRIGHT;
  const extensionTriggeredRecording = isRecording && recordingSource === RECORDING_SOURCE.EXTENSION_TRIGGERED;

  chrome.storage.local.set({
    isRecording: playwrightRecording,
    recordingId: playwrightRecording ? recordingId : null,
    recordingSource: isRecording ? recordingSource : null,
    extensionTriggeredRecording: extensionTriggeredRecording,
    extensionTriggeredRecordingId: extensionTriggeredRecording ? recordingId : null
  });
}

function restoreRecordingState() {
  chrome.storage.local.get(STORAGE_KEYS, (state) => {
    const restoredState = resolvePersistedRecordingState(state);
    isRecording = restoredState.isRecording;
    recordingId = restoredState.recordingId;
    recordingSource = restoredState.recordingSource;
    hasLoadedPersistedState = true;
  });
}

// 立即初始化并连接（使用默认 URL，稍后可通过 CDP 注入更新）
wsClient = new WebSocketClient(WEBSOCKET_URL);
attachWsClientHandlers();
restoreRecordingState();
applyWsClientMetadata();

function buildWsClientMetadata(overrides = {}) {
  return {
    client_kind: launchContext.client_kind || 'extension_background',
    launch_token: launchContext.launch_token || null,
    recording_id: launchContext.recording_id || null,
    ...overrides,
  };
}

function applyWsClientMetadata(overrides = {}) {
  if (!wsClient || typeof wsClient.setClientMetadata !== 'function') {
    return;
  }

  wsClient.setClientMetadata(buildWsClientMetadata(overrides));
}

function handleAppReply(data) {
  if (data.type !== 'recording_control_reply') {
    return;
  }

  chrome.runtime.sendMessage({
    type: 'RECORDING_CONTROL_REPLY',
    status: data.status,
    recording_id: data.recording_id,
    error: data.error,
  }).catch(() => {});

  if (data.status === 'started') {
    setRecordingState(true, data.recording_id, RECORDING_SOURCE.EXTENSION_TRIGGERED);
    // 通知所有标签页开始录制
    notifyAllTabs({ type: 'START_RECORDING', recording_id: data.recording_id });
  } else if (data.status === 'stopped') {
    setRecordingState(false, null, null);
    networkRequests.clear();
    notifyAllTabs({ type: 'STOP_RECORDING' });
  }
}

function isRecordableTab(tab) {
  const tabUrl = tab && typeof tab.url === 'string' ? tab.url : '';
  return Boolean(tabUrl)
    && !tabUrl.startsWith('chrome://')
    && !tabUrl.startsWith('chrome-extension://')
    && tabUrl !== 'about:blank';
}

function notifyAllTabs(message) {
  chrome.tabs.query({}, (tabs) => {
    tabs.forEach(tab => {
      if (!isRecordableTab(tab)) return;
      chrome.tabs.sendMessage(tab.id, message).catch(() => {});
    });
  });
}

function attachWsClientHandlers() {
  if (!wsClient) {
    return;
  }
  wsClient.onControlStart = handleControlStart;
  wsClient.onControlStop = handleControlStop;
  wsClient.onControlReply = handleAppReply;
}

// ⭐ 监听来自 Content Script 的配置消息
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'init_config') {
    const config = message.config;
    if (config && config.websocketUrl) {
      console.log('[BACKGROUND] 收到 CDP 注入的配置:', config);
      const metadataOverrides = {
        recording_id: config.recordingId || launchContext.recording_id || null,
      };

      // 更新 WebSocket URL
      const newUrl = config.websocketUrl;
      if (newUrl !== WEBSOCKET_URL) {
        console.log(`[BACKGROUND] 更新 WebSocket URL: ${WEBSOCKET_URL} → ${newUrl}`);

        // 关闭旧连接
        if (wsClient && wsClient.ws) {
          wsClient.ws.close();
        }

        // 创建新连接
        WEBSOCKET_URL = newUrl;
        wsClient = new WebSocketClient(WEBSOCKET_URL);
        attachWsClientHandlers();
        applyWsClientMetadata(metadataOverrides);
        wsClient.connect();

        sendResponse({ success: true, message: 'WebSocket URL 已更新' });
      } else {
        applyWsClientMetadata(metadataOverrides);
        console.log('[BACKGROUND] WebSocket URL 未变化，无需更新');
        sendResponse({ success: true, message: 'WebSocket URL 相同' });
      }
    }
  }
  return true;  // 保持消息通道开放以支持异步响应
});

// 设置回调
function handleControlStart(message) {
  setRecordingState(true, message.recording_id, RECORDING_SOURCE.PLAYWRIGHT);
  console.log('[BACKGROUND] ⭐️ 开始录制:', recordingId);  // 保留：关键日志

  // 查询所有标签页
  chrome.tabs.query({}, (tabs) => {
    tabs.forEach(tab => {
      if (!isRecordableTab(tab)) {
        return;
      }

      // 先尝试发送消息（如果 content script 已注入）
      chrome.tabs.sendMessage(tab.id, {
        type: 'START_RECORDING',
        recording_id: recordingId
      }, (response) => {
        if (chrome.runtime.lastError) {
          // Content script 还没有注入，动态注入
          chrome.scripting.executeScript({
            target: { tabId: tab.id },
            files: ['content_script_simple.js']
          }, () => {
            if (chrome.runtime.lastError) {
              console.error('[BACKGROUND] 注入失败:', chrome.runtime.lastError.message);
            } else {
              // 注入成功后，再次发送开始录制消息
              setTimeout(() => {
                chrome.tabs.sendMessage(tab.id, {
                  type: 'START_RECORDING',
                  recording_id: recordingId
                }).catch(err => {
                  console.error('[BACKGROUND] 发送 START_RECORDING 失败:', err);
                });
              }, 100);
            }
          });
        }
      });
    });
  });
}

function handleControlStop(message) {
  setRecordingState(false, null, null);
  console.log('[BACKGROUND] ⏹️ 停止录制');  // 保留：关键日志

  // 清理网络请求缓存
  networkRequests.clear();
  notifyAllTabs({ type: 'STOP_RECORDING' });
}

// 连接
wsClient.connect();
// console.log('[BACKGROUND] WebSocket 客户端已初始化');

// 监听所有网络请求
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (isRecording) {
      const request = {
        url: details.url,
        method: details.method,
        type: details.type,  // ⭐ 新增：保存请求类型（stylesheet, script, image, xmlhttprequest, other 等）
        timestamp: details.timeStamp / 1000.0,
        request_headers: {}
      };

      try {
        const origin = new URL(details.url).origin;
        storeNetworkRequest(origin, request);
      } catch (e) {
        console.error('[BACKGROUND] URL解析失败:', e);
      }
    }
  },
  { urls: ["<all_urls>"] },
  []
);

// 监听所有网络响应
chrome.webRequest.onCompleted.addListener(
  (details) => {
    if (isRecording) {
      // ⭐ 调试日志：记录所有请求的类型
      if (details.url.includes('sugrec') || details.url.includes('api')) {
        console.log('[BACKGROUND] 📥 请求完成:', {
          type: details.type,
          method: details.method,
          url: details.url.substring(0, 100),
          status: details.statusCode
        });
      }

      try {
        const origin = new URL(details.url).origin;
        const requests = networkRequests.get(origin);
        if (requests && requests.length > 0) {
          // 查找匹配的请求（从后往前找）
          for (let i = requests.length - 1; i >= 0; i--) {
            if (requests[i].url === details.url) {
              requests[i].response_status = details.statusCode;
              requests[i].response_headers = {};
              requests[i].duration = (details.timeStamp / 1000.0) - requests[i].timestamp;

              // 标记需要从 content script 获取响应体
              // ⭐ 扩展：对所有可能的 XHR/fetch 类型都尝试捕获
              const needsCapture = ['xmlhttprequest', 'other', 'ping'].includes(details.type);
              if (needsCapture) {
                requests[i].needs_body_capture = true;
                console.log('[BACKGROUND] ✅ 标记需要捕获响应体:', details.type, details.url.substring(0, 80));
              } else {
                console.log('[BACKGROUND] ❌ 跳过响应体捕获:', details.type, details.url.substring(0, 80));
              }

              break;
            }
          }
        }
      } catch (e) {
        console.error('[BACKGROUND] URL解析失败:', e);
      }
    }
  },
  { urls: ["<all_urls>"] },
  []  // 注意：不使用 extraInfoSpec 来获取响应体，因为会破坏加密连接
);

// ⭐ 监听标签页创建（仅用于日志记录）
chrome.tabs.onCreated.addListener((tab) => {
  console.log('[BACKGROUND] 🆕 新标签页已创建:', tab.id, 'URL:', tab.url || '(空)');
  // 注意：不在这里注入，因为新标签页的 URL 可能还是 about:blank 或空的
  // 实际的注入在 onUpdated 的 loading 状态进行
});

// ⭐ 监听标签页更新（在页面开始加载时就注入）
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  // ⭐ 关键修复：在 loading 状态就开始注入，而不是等到 complete
  if (changeInfo.status === 'loading' && tab.url) {
    if (!isRecordableTab(tab)) {
      console.log('[BACKGROUND] ⏭️  跳过特殊页面:', tab.url);
      return;
    }

    console.log('[BACKGROUND] 🔄 标签页开始加载:', tabId, tab.url);

    // 如果正在录制，立即注入 content scripts
    if (isRecording && recordingId) {
      console.log('[BACKGROUND] ⚡ 正在录制，立即注入 content scripts');

      // ⭐ 先尝试直接发送消息（可能 manifest 已经自动注入了）
      chrome.tabs.sendMessage(tabId, {
        type: 'START_RECORDING',
        recording_id: recordingId
      }, (response) => {
        if (chrome.runtime.lastError) {
          // Manifest 没有自动注入（或还没注入完成），手动注入
          console.log('[BACKGROUND] 📝 Content script 未就绪，手动注入 ISOLATED world');

          // ⭐ 关键：必须先注入 ISOLATED world（它可以访问 chrome API）
          chrome.scripting.executeScript({
            target: { tabId: tabId },
            files: ['content_script_isolated.js']
          }, () => {
            if (chrome.runtime.lastError) {
              console.error('[BACKGROUND] ❌ 注入 ISOLATED world 失败:', chrome.runtime.lastError.message);
            } else {
              console.log('[BACKGROUND] ✅ ISOLATED world 注入成功');

              // ⭐ 立即注入 MAIN world（用于拦截 fetch/XHR）
              chrome.scripting.executeScript({
                target: { tabId: tabId },
                files: ['content_script_main.js'],
                world: 'MAIN'  // ⭐ 关键：必须在 MAIN world 中
              }, () => {
                if (chrome.runtime.lastError) {
                  console.error('[BACKGROUND] ❌ 注入 MAIN world 失败:', chrome.runtime.lastError.message);
                } else {
                  console.log('[BACKGROUND] ✅ MAIN world 注入成功');

                  // ⭐ 注入完成后立即发送 START_RECORDING 消息
                  setTimeout(() => {
                    chrome.tabs.sendMessage(tabId, {
                      type: 'START_RECORDING',
                      recording_id: recordingId
                    }, (response) => {
                      if (chrome.runtime.lastError) {
                        console.error('[BACKGROUND] ❌ 发送 START_RECORDING 失败:', chrome.runtime.lastError.message);
                      } else {
                        console.log('[BACKGROUND] ✅ 新标签页已开始录制（手动注入）');
                      }
                    });
                  }, 50);  // 减少等待时间到 50ms，因为我们在 loading 状态就已经注入了
                }
              });
            }
          });
        } else {
          console.log('[BACKGROUND] ✅ 新标签页已开始录制（manifest 自动注入）');
        }
      });
    }
  }

  // ⭐ 保留 complete 状态的处理（用于日志记录和备用注入）
  if (changeInfo.status === 'complete' && tab.url) {
    console.log('[BACKGROUND] ✅ 标签页加载完成:', tabId, tab.url);

    // 如果正在录制，再次确认录制状态（备用机制）
    if (isRecording && recordingId) {
      // 发送消息确认录制状态（不强制注入，因为之前已经在 loading 状态注入了）
      chrome.tabs.sendMessage(tabId, {
        type: 'START_RECORDING',
        recording_id: recordingId
      }).catch(() => {
        // 如果失败，说明 content script 可能没有注入成功，尝试再次注入
        console.log('[BACKGROUND] ⚠️  complete 状态时消息发送失败，尝试再次注入');
      });
    }
  }
});

// 监听来自 content script 的消息
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'RECORDING_EVENT') {
    if (!isRecording) {
      sendResponse({ success: false, ignored: true });
      return true;
    }

    let event = message.event;


    // ⭐ 新增：关联网络请求（如果有 URL）
    if (event.url) {
      try {
        const url = new URL(event.url);
        const origin = url.origin;
        const requests = networkRequests.get(origin) || [];


        if (requests.length > 0) {
          event.network_requests = requests.map(req => ({
            url: req.url,
            method: req.method,
            type: req.type,  // ⭐ 新增：请求类型
            request_headers: req.request_headers || {},
            request_body: req.request_body || null,
            response_status: req.response_status || null,
            response_headers: req.response_headers || {},
            response_body: req.response_body || null,
            timestamp: req.timestamp,
            duration: req.duration || null
          }));

        }
      } catch (e) {
        console.error('[BACKGROUND] ❌ URL解析失败:', e);
      }
    }

    // 通过 WebSocket 发送到 Python
    if (wsClient && wsClient.connected) {
      wsClient.sendAction(event);
    }
    sendResponse({ success: true });
  } else if (message.type === 'NETWORK_REQUEST') {
    // 处理来自 content script 的网络请求捕获
    console.log('[BACKGROUND] 📩 收到 NETWORK_REQUEST 消息, isRecording =', isRecording);

    if (isRecording) {
      const request = message.request;

      // ⭐ 调试：显示详细信息
      const hasResponseBody = request.response_body && request.response_body.length > 0;
      const hasRequestBody = request.request_body && request.request_body.length > 0;
      console.log('[BACKGROUND] 📥 网络请求:', request.method, request.url.substring(0, 100),
                 '| 有请求体:', hasRequestBody, '| 有响应体:', hasResponseBody,
                 '| 响应体长度:', request.response_body?.length || 0);

      // ⭐ 新增：立即通过 WebSocket 发送到 Python
      if (wsClient && wsClient.connected) {
        // 构造一个网络请求事件
        const networkEvent = {
          action_type: 'network_request',
          url: request.url,
          timestamp: request.timestamp,
          parameters: {
            method: request.method,
            request_type: request.request_type || 'xmlhttprequest',  // ⭐ 新增：请求类型
            request_headers: request.request_headers,
            request_body: request.request_body,
            response_status: request.response_status,
            response_headers: request.response_headers,
            response_body: request.response_body,
            duration: request.duration
          },
          network_requests: []  // 网络请求本身不需要关联其他网络请求
        };

        wsClient.sendAction(networkEvent);
        // console.log('[BACKGROUND] ✅ 网络请求已通过 WebSocket 发送到 Python');
      } else {
        console.warn('[BACKGROUND] ⚠️ WebSocket 未连接，网络请求无法发送');
      }

      // 同时也存储到缓存（用于关联到 DOM 事件）
      const urlObj = new URL(request.url);
      const origin = urlObj.origin;
      storeNetworkRequest(origin, request);
    }

    sendResponse({ success: true });
    return true;
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'GET_RECORDING_STATE') {
    if (hasLoadedPersistedState) {
      sendResponse({
        isRecording: isRecording,
        recordingId: recordingId,
        recordingSource: recordingSource,
        actionCount: 0,
      });
      return true;
    }
    chrome.storage.local.get(STORAGE_KEYS, (state) => {
      const resolvedState = resolvePersistedRecordingState(state);
      sendResponse({
        isRecording: resolvedState.isRecording,
        recordingId: resolvedState.recordingId,
        recordingSource: resolvedState.recordingSource,
        actionCount: 0,
      });
    });
    return true;
  }

  if (message.type === 'GET_WS_STATUS') {
    if (wsClient) {
      wsClient.ensureConnected();
    }
    sendResponse({ connected: isWsConnected() });
    return true;
  }

  if (message.type === 'EXTENSION_START_RECORDING') {
    sendControlAction('start', 'App 未连接，请先启动 Mexemplar', sendResponse);
    return true;
  }

  if (message.type === 'EXTENSION_STOP_RECORDING') {
    sendControlAction('stop', 'App 未连接', sendResponse);
    return true;
  }

  if (message.type === 'START_RECORDING') {
    sendResponse({ success: false, error: '请从 Mexemplar App 中启动 Playwright 录制' });
    return true;
  }

  if (message.type === 'STOP_RECORDING') {
    sendResponse({ success: false, error: 'Playwright 录制请从 Mexemplar App 中停止' });
    return true;
  }

  if (message.type === 'EXPORT_RECORDING') {
    sendResponse({ success: false, error: '当前版本不支持从扩展弹窗导出录制' });
    return true;
  }

  return false;
});
