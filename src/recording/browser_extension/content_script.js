// Content Script - 注入到页面中，捕获DOM事件
(function() {
  'use strict';
  
  try {
    // 立即记录content script开始执行（用于调试）
    // 使用多种方式记录，确保能被检测到
    console.log('[MEXEMPLAR] Content script execution started', window.location.href);
    // 设置一个全局标记，方便通过CDP检测
    window.__mexemplar_content_script_loaded__ = true;
    
    // 避免重复注入
    if (window.__mexemplar_recorder_injected__) {
      console.log('[MEXEMPLAR] Content script already injected, skipping', window.location.href);
      return;
    }
    window.__mexemplar_recorder_injected__ = true;

    // 创建日志显示面板（已删除，不再使用）
    // createLogPanel();

  let isRecording = false;
  let recordingStartTime = null;
  
  // 拖拽状态跟踪
  let dragSource = null;
  let dragStartElement = null;
  
  // 滚动防抖定时器
  let scrollTimeout = null;

  // 鼠标移动采样（每100ms采样一次）
  let lastMouseMoveTime = 0;
  const MOUSE_MOVE_SAMPLE_INTERVAL = 100; // 毫秒

  // 生成元素定位信息
  function getElementLocator(element) {
    if (!element) return null;
    
    // 生成XPath
    function getXPath(element) {
      if (element.id !== '') {
        return `//*[@id="${element.id}"]`;
      }
      if (element === document.body) {
        return '/html/body';
      }
      let ix = 0;
      const siblings = element.parentNode.childNodes;
      for (let i = 0; i < siblings.length; i++) {
        const sibling = siblings[i];
        if (sibling === element) {
          return getXPath(element.parentNode) + '/' + 
                 element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
        }
        if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {
          ix++;
        }
      }
    }
    
    // 生成CSS Selector
    function getCSSSelector(element) {
      if (element.id) {
        return `#${element.id}`;
      }
      if (element.className && typeof element.className === 'string') {
        const classes = element.className.split(' ').filter(c => c).join('.');
        if (classes) {
          return `${element.tagName.toLowerCase()}.${classes}`;
        }
      }
      return element.tagName.toLowerCase();
    }
    
    try {
      const rect = element.getBoundingClientRect();
      const attributes = {};
      for (let attr of element.attributes) {
        attributes[attr.name] = attr.value;
      }
      
      return {
        xpath: getXPath(element),
        css_selector: getCSSSelector(element),
        tag_name: element.tagName,
        id: element.id || null,
        className: element.className || null,
        text_content: element.textContent ? element.textContent.trim().substring(0, 100) : null,
        attributes: attributes,
        bounding_box: {
          x: rect.x,
          y: rect.y,
          width: rect.width,
          height: rect.height
        }
      };
    } catch (e) {
      return null;
    }
  }
  
  // 提取鼠标事件的完整坐标信息
  function getMouseCoordinates(e) {
    return {
      // 相对于视口（浏览器窗口）的坐标
      clientX: e.clientX,
      clientY: e.clientY,
      // 相对于整个文档的坐标（包含滚动偏移）
      pageX: e.pageX !== undefined ? e.pageX : (e.clientX + (window.scrollX || window.pageXOffset || 0)),
      pageY: e.pageY !== undefined ? e.pageY : (e.clientY + (window.scrollY || window.pageYOffset || 0)),
      // 相对于屏幕的坐标
      screenX: e.screenX !== undefined ? e.screenX : null,
      screenY: e.screenY !== undefined ? e.screenY : null,
      // 相对于目标元素的坐标
      offsetX: e.offsetX !== undefined ? e.offsetX : null,
      offsetY: e.offsetY !== undefined ? e.offsetY : null
    };
  }
  
  // 发送事件到background
  // 辅助函数：发送日志到 background script（已禁用以提升性能）
  function sendDebugLog(location, message, data, hypothesisId) {
    // 已禁用：频繁的调试日志会阻塞页面加载
    return;
    /* 原来的代码已注释
    try {
      chrome.runtime.sendMessage({
        type: 'DEBUG_LOG',
        location: location,
        message: message,
        data: data || {},
        timestamp: Date.now(),
        sessionId: 'debug-session',
        runId: 'run1',
        hypothesisId: hypothesisId
      }).catch(() => {});
      console.log(`[DEBUG] ${location}: ${message}`, data);
    } catch(e) {}
    */
  }

  function sendEvent(eventData) {
    if (!isRecording) {
      return;
    }

    try {
      const fullEvent = {
        ...eventData,
        timestamp: Date.now() / 1000.0,
        url: window.location.href
      };

      // 通过 chrome.runtime.sendMessage 发送到 background.js
      // background.js 会通过 WebSocket 发送到 Python
      chrome.runtime.sendMessage({
        type: 'RECORDING_EVENT',
        event: fullEvent
      }, (response) => {
        if (chrome.runtime.lastError) {
          console.error('[MEXEMPLAR] Failed to send event:', chrome.runtime.lastError);
        } else {
          console.log('[MEXEMPLAR] Event sent:', fullEvent.action_type);
        }
      });

    } catch (e) {
      console.error('[MEXEMPLAR] Error in sendEvent:', e);
    }
  }
  
  // 监听点击事件
  document.addEventListener('click', function(e) {
    // #region agent log
    sendDebugLog('content_script.js:178', 'click event captured', {isRecording: isRecording, tagName: e.target.tagName}, 'H1');
    // #endregion
    const target = e.target;
    sendEvent({
      action_type: 'click',
      dom_element: getElementLocator(target),
      parameters: {
        ...getMouseCoordinates(e),
        button: e.button // 0=左键, 1=中键, 2=右键
      }
    });
  }, true);
  
  // 监听双击事件
  document.addEventListener('dblclick', function(e) {
    const target = e.target;
    sendEvent({
      action_type: 'dblclick',
      dom_element: getElementLocator(target),
      parameters: {
        ...getMouseCoordinates(e),
        button: e.button
      }
    });
  }, true);
  
  // 监听右键点击事件
  document.addEventListener('contextmenu', function(e) {
    const target = e.target;
    sendEvent({
      action_type: 'contextmenu',
      dom_element: getElementLocator(target),
      parameters: {
        ...getMouseCoordinates(e),
        button: e.button
      }
    });
  }, true);
  
  // 监听输入事件
  document.addEventListener('input', function(e) {    const target = e.target;
    sendEvent({
      action_type: 'fill',
      dom_element: getElementLocator(target),
      parameters: {
        value: target.value || null
      }
    });
  }, true);
  
  // 判断是否为字符键（需要过滤，避免与input事件重复）
  function isCharacterKey(key, keyCode) {
    // 字符键通常是可打印字符（A-Z, a-z, 0-9, 标点符号等）
    // 排除功能键、修饰键、导航键等
    if (key && key.length === 1) {
      return true; // 单个字符，通常是可打印字符
    }
    // 常见的非字符键
    const nonCharacterKeys = [
      'Tab', 'Enter', 'Shift', 'Control', 'Alt', 'Meta', 'CapsLock',
      'Escape', 'Space', 'PageUp', 'PageDown', 'End', 'Home',
      'ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown',
      'Insert', 'Delete', 'Backspace', 'F1', 'F2', 'F3', 'F4',
      'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12'
    ];
    return !nonCharacterKeys.includes(key);
  }
  
  // 监听键盘按下事件
  document.addEventListener('keydown', function(e) {
    const target = e.target;
    
    // 只记录非字符键或快捷键组合（避免与input事件重复）
    // 如果同时按下修饰键（Ctrl/Alt/Shift/Meta），则记录
    const hasModifier = e.ctrlKey || e.altKey || e.shiftKey || e.metaKey;
    const isSpecialKey = !isCharacterKey(e.key, e.keyCode);
    
    if (hasModifier || isSpecialKey) {
      sendEvent({
        action_type: 'keydown',
        dom_element: getElementLocator(target),
        parameters: {
          key: e.key,
          code: e.code,
          keyCode: e.keyCode,
          which: e.which,
          ctrlKey: e.ctrlKey,
          altKey: e.altKey,
          shiftKey: e.shiftKey,
          metaKey: e.metaKey
        }
      });
    }
  }, true);
  
  // 监听键盘释放事件
  document.addEventListener('keyup', function(e) {
    const target = e.target;
    
    // 只记录非字符键或快捷键组合
    const hasModifier = e.ctrlKey || e.altKey || e.shiftKey || e.metaKey;
    const isSpecialKey = !isCharacterKey(e.key, e.keyCode);
    
    if (hasModifier || isSpecialKey) {
      sendEvent({
        action_type: 'keyup',
        dom_element: getElementLocator(target),
        parameters: {
          key: e.key,
          code: e.code,
          keyCode: e.keyCode,
          which: e.which,
          ctrlKey: e.ctrlKey,
          altKey: e.altKey,
          shiftKey: e.shiftKey,
          metaKey: e.metaKey
        }
      });
    }
  }, true);
  
  // 监听选择变化事件
  document.addEventListener('change', function(e) {
    const target = e.target;
    if (target.tagName === 'SELECT') {
      sendEvent({
        action_type: 'select',
        dom_element: getElementLocator(target),
        parameters: {
          value: target.value,
          selectedOptions: Array.from(target.selectedOptions).map(opt => opt.value)
        }
      });
    }
  }, true);
  
  // 监听表单提交事件
  document.addEventListener('submit', function(e) {
    const target = e.target;
    if (target.tagName === 'FORM') {
      // 收集表单数据
      const formData = {};
      try {
        const form = target;
        const inputs = form.querySelectorAll('input, select, textarea');
        inputs.forEach(input => {
          if (input.name) {
            if (input.type === 'checkbox' || input.type === 'radio') {
              if (input.checked) {
                formData[input.name] = input.value || 'checked';
              }
            } else {
              formData[input.name] = input.value || '';
            }
          }
        });
      } catch (err) {
        // 忽略表单数据收集错误
      }
      
      sendEvent({
        action_type: 'submit',
        dom_element: getElementLocator(target),
        parameters: {
          formData: formData,
          action: target.action || null,
          method: target.method || 'get'
        }
      });
    }
  }, true);
  
  // 监听拖拽开始事件
  document.addEventListener('dragstart', function(e) {
    const target = e.target;
    dragSource = target;
    dragStartElement = getElementLocator(target);
    sendEvent({
      action_type: 'dragstart',
      dom_element: dragStartElement,
      parameters: {
        ...getMouseCoordinates(e)
      }
    });
  }, true);
  
  // 监听拖拽结束事件
  document.addEventListener('dragend', function(e) {
    if (dragSource) {
      sendEvent({
        action_type: 'dragend',
        dom_element: dragStartElement,
        parameters: {
          ...getMouseCoordinates(e)
        }
      });
      dragSource = null;
      dragStartElement = null;
    }
  }, true);
  
  // 监听拖拽放置事件
  document.addEventListener('drop', function(e) {
    const target = e.target;
    if (dragSource) {
      sendEvent({
        action_type: 'drop',
        dom_element: getElementLocator(target),
        parameters: {
          ...getMouseCoordinates(e),
          dragSource: dragStartElement // 保存拖拽源元素信息
        }
      });
      dragSource = null;
      dragStartElement = null;
    }
  }, true);
  
  // 监听滚动事件（使用防抖优化）
  window.addEventListener('scroll', function(e) {
    if (!isRecording) return;
    
    // 清除之前的定时器
    if (scrollTimeout) {
      clearTimeout(scrollTimeout);
    }
    
    // 防抖：只在滚动停止150ms后记录
    scrollTimeout = setTimeout(function() {
      // 获取滚动目标（可能是window或某个元素）
      const scrollTarget = e.target === document ? window : e.target;
      let scrollElement = null;
      let scrollX = 0;
      let scrollY = 0;
      
      if (scrollTarget === window) {
        scrollX = window.scrollX || window.pageXOffset || 0;
        scrollY = window.scrollY || window.pageYOffset || 0;
        scrollElement = getElementLocator(document.documentElement);
      } else if (scrollTarget instanceof Element) {
        scrollX = scrollTarget.scrollLeft || 0;
        scrollY = scrollTarget.scrollTop || 0;
        scrollElement = getElementLocator(scrollTarget);
      }
      
      if (scrollElement) {
        sendEvent({
          action_type: 'scroll',
          dom_element: scrollElement,
          parameters: {
            scrollX: scrollX,
            scrollY: scrollY
          }
        });
      }
      
      scrollTimeout = null;
    }, 150);
  }, true);
  
  // 监听鼠标移动事件（采样捕获，可选）
  // 注意：数据量很大，默认每100ms采样一次
  document.addEventListener('mousemove', function(e) {
    if (!isRecording) return;
    
    const now = Date.now();
    if (now - lastMouseMoveTime >= MOUSE_MOVE_SAMPLE_INTERVAL) {
      const target = e.target;
      sendEvent({
        action_type: 'mousemove',
        dom_element: getElementLocator(target),
        parameters: {
          ...getMouseCoordinates(e)
        }
      });
      lastMouseMoveTime = now;
    }
  }, true);
  
  // 监听导航事件（通过popstate和pushState/replaceState）
  window.addEventListener('popstate', function() {
    sendEvent({
      action_type: 'navigate',
      url: window.location.href
    });
  });
  
  // 拦截pushState和replaceState来捕获程序化导航
  const originalPushState = history.pushState;
  const originalReplaceState = history.replaceState;
  
  history.pushState = function() {
    originalPushState.apply(history, arguments);
    sendEvent({
      action_type: 'navigate',
      url: window.location.href
    });
  };
  
  history.replaceState = function() {
    originalReplaceState.apply(history, arguments);
    sendEvent({
      action_type: 'navigate',
      url: window.location.href
    });
  };
  
  // 监听页面卸载前的导航
  window.addEventListener('beforeunload', function() {
    sendEvent({
      action_type: 'navigate',
      url: window.location.href
    });
  });
  
  // 监听来自background的消息
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    // 处理 background script 的日志消息（方便调试，因为 Service Worker 控制台看不到）
    if (message.type === 'BACKGROUND_LOG') {
      const level = message.level || 'log';
      const msg = message.message || '';
      const data = message.data;
      
      // 在控制台输出
      switch (level) {
        case 'error':
          console.error(msg, data || '');
          break;
        case 'warn':
          console.warn(msg, data || '');
          break;
        case 'success':
          console.log('%c' + msg, 'color: green; font-weight: bold', data || '');
          break;
        case 'info':
        default:
          console.log(msg, data || '');
          break;
      }

      // 黑框日志面板已删除，不再在页面上显示日志
      // showLogOnPage(level, msg, data, message.timestamp);

      return true;
    }
    
    if (message.type === 'PING') {
      // PING消息用于检测content script是否已注入
      sendResponse({ success: true, injected: true });
      return true;
    } else if (message.type === 'START_RECORDING') {
      // #region agent log
      sendDebugLog('content_script.js:528', 'START_RECORDING received in content script', {previousIsRecording: isRecording, recordingId: message.recording_id}, 'H0');
      // #endregion
      
      isRecording = true;
      recordingStartTime = Date.now() / 1000.0;
      
      // #region agent log
      sendDebugLog('content_script.js:533', 'isRecording set to true in content script', {isRecording: isRecording}, 'H0');
      // #endregion
      
      sendResponse({ success: true });
    } else if (message.type === 'STOP_RECORDING') {
      isRecording = false;      sendResponse({ success: true });
    } else if (message.type === 'GET_RECORDING_STATE') {
      sendResponse({ isRecording, recordingStartTime });
    } else if (message.type === 'GET_RECORDED_ACTIONS') {
      // 转发到background script
      chrome.runtime.sendMessage({ type: 'GET_RECORDED_ACTIONS' }, (response) => {
        sendResponse(response || { actions: [] });
      });
      return true;
    }
    return true;
  });
  
  // 监听来自页面的消息（用于CDP降级方案）
  window.addEventListener('message', (event) => {
    // #region agent log
    sendDebugLog('content_script.js:564', 'window message event received', {eventType: event.data?.type, origin: event.origin}, 'H0');
    // #endregion
    
    if (event.data && event.data.type === 'MEXEMPLAR_START_RECORDING') {
      // #region agent log
      sendDebugLog('content_script.js:568', 'MEXEMPLAR_START_RECORDING message received', {recordingId: event.data.recording_id}, 'H0');
      // #endregion
      
      // 转发START_RECORDING消息到background script
      chrome.runtime.sendMessage({
        type: 'START_RECORDING',
        recording_id: event.data.recording_id
      }, (response) => {
        // #region agent log
        sendDebugLog('content_script.js:572', 'START_RECORDING sent to background', {response: response}, 'H0');
        // #endregion
      });
    } else if (event.data && event.data.type === 'MEXEMPLAR_GET_ACTIONS') {
      // 通过chrome.runtime.sendMessage获取actions
      chrome.runtime.sendMessage({ type: 'GET_RECORDED_ACTIONS' }, (response) => {
        // 发送响应回页面
        window.postMessage({
          type: 'MEXEMPLAR_ACTIONS_RESPONSE',
          messageId: event.data.messageId,
          actions: response && response.actions ? response.actions : []
        }, '*');
      });
    }
  });

  // 暴露一个全局函数，供CDP调用（在isolated world中）
  window.__mexemplar_start_recording__ = function(recordingId) {
    // 转发START_RECORDING消息到background script
    chrome.runtime.sendMessage({
      type: 'START_RECORDING',
      recording_id: recordingId
    }, (response) => {
      // 响应处理
    });
  };

  // ❌ 已删除自动启动录制逻辑（会导致 recording_id 不匹配）
  // Python 负责发送 START_RECORDING 消息并传递正确的 recording_id
  // Content Script 不应该自动启动录制

  console.log('[MEXEMPLAR] Content script initialized', { isRecording, url: window.location.href });

  // ⭐️ 定期检查 chrome.storage.local，看是否收到录制命令
  const checkInterval = setInterval(() => {
    // 检查扩展上下文是否有效
    if (!chrome || !chrome.runtime) {
      clearInterval(checkInterval);
      console.log('[MEXEMPLAR] 扩展上下文已失效，停止检查');
      return;
    }

    try {
      chrome.storage.local.get(['mexemplar_debug_last_command', 'mexemplar_debug_recording_id', 'mexemplar_debug_timestamp'], (result) => {
        // 检查是否因为扩展重新加载而报错
        if (chrome.runtime.lastError) {
          clearInterval(checkInterval);
          console.log('[MEXEMPLAR] 扩展已重新加载，停止检查');
          return;
        }

        if (result.mexemplar_debug_last_command === 'control_start' && !isRecording) {
          console.log('[MEXEMPLAR] 🔍 检测到录制命令（通过 storage）:', result.mexemplar_debug_recording_id);
          console.log('[MEXEMPLAR] ⚠️ 但是 content_script 没有通过 chrome.runtime 收到 START_RECORDING 消息！');
        }
      });
    } catch (error) {
      clearInterval(checkInterval);
      console.log('[MEXEMPLAR] 扩展上下文已失效:', error.message);
    }
  }, 1000);


} catch (error) {
  // 捕获content script执行错误
  console.error('[MEXEMPLAR] Content script execution error:', error);
}
})();

