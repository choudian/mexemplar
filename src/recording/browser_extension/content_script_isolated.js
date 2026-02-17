// Content Script - ISOLATED World
// 负责事件监听、DOM 操作、与 background 通信
(function() {
  'use strict';

  // console.log('[ISOLATED] Content script (ISOLATED world) 已加载');

  let isRecording = false;
  let recordingStartTime = null;
  let recordingId = null;

  // 避免重复注入
  if (window.__mexemplar_isolated_injected__) {
    return;
  }
  window.__mexemplar_isolated_injected__ = true;

  // ⭐ 关键修复：立即从 chrome.storage 读取录制状态
  chrome.storage.local.get(['isRecording', 'recordingId'], (result) => {
    if (result.isRecording) {
      console.log('[ISOLATED] ✅ 从 storage 读取到录制状态:', result.recordingId);
      // 立即设置本地状态
      isRecording = result.isRecording;
      recordingId = result.recordingId;

      // ⭐ 立即通知 MAIN world（不等待任何消息）
      window.postMessage({
        type: 'MEXEMPLAR_SET_RECORDING',
        isRecording: isRecording,
        recordingId: recordingId
      }, '*');
      console.log('[ISOLATED] ✅ 已立即通知 MAIN world 开始录制');
    } else {
      console.log('[ISOLATED] ℹ️  当前不在录制状态');
    }
  });

  // ⭐ 读取 CDP 注入的配置并发送到 Background Script
  const injectedConfig = window.MEXEMPLAR_CONFIG;
  if (injectedConfig) {
    console.log('[ISOLATED] 检测到 CDP 注入的配置，发送到 Background:', injectedConfig);

    // 立即发送给 Background Script（ISOLATED world 可以访问 chrome.runtime）
    chrome.runtime.sendMessage({
      type: 'init_config',
      config: injectedConfig
    }, (response) => {
      if (chrome.runtime.lastError) {
        console.warn('[ISOLATED] 发送配置失败:', chrome.runtime.lastError.message);
      } else {
        console.log('[ISOLATED] 配置已发送至 Background Script', response);
      }
    });
  }

  // ========================================================================
  // DOM 序列化工具函数（来自 dom_serializer.js）
  // ========================================================================

  /**
   * 截断文本
   */
  function truncateText(text, maxLength) {
    if (!text || text.length <= maxLength) {
      return text;
    }
    return text.substring(0, maxLength) + '...';
  }

  /**
   * 捕获兄弟元素
   * @param {Element} element - 目标元素
   * @returns {Object|null} 兄弟元素信息
   */
  function captureSiblings(element) {
    const parent = element.parentElement;
    if (!parent) {
      return null;
    }

    const siblings = Array.from(parent.children);
    const clickedIndex = siblings.indexOf(element);

    return {
      container_selector: generateSelector(parent),
      item_selector: generateSelector(element).split(' > ').pop(),
      list_type: detectListType(parent),
      clicked_index: clickedIndex + 1,  // 1-indexed
      total_count: siblings.length,
      siblings: siblings.map((sibling, index) => captureSiblingInfo(sibling, index)),
    };
  }

  /**
   * 检测列表类型
   */
  function detectListType(parent) {
    const tag = parent.tagName.toLowerCase();
    const display = window.getComputedStyle(parent).display;

    if (tag === 'ul' || tag === 'ol') {
      return 'list';
    }
    if (tag === 'table') {
      return 'table';
    }
    if (display === 'grid') {
      return 'grid';
    }
    if (display === 'flex') {
      const flexDirection = window.getComputedStyle(parent).flexDirection;
      return flexDirection === 'column' ? 'list' : 'grid';
    }

    return 'unknown';
  }

  /**
   * 捕获单个兄弟元素信息
   */
  function captureSiblingInfo(element, index) {
    const rect = element.getBoundingClientRect();
    const link = element.querySelector('a') || (element.tagName === 'A' ? element : null);
    const image = element.querySelector('img') || (element.tagName === 'IMG' ? element : null);

    return {
      index: index + 1,
      tag: element.tagName.toLowerCase(),
      class_list: element.className ? element.className.split(/\s+/).filter(c => c) : [],
      text_summary: truncateText(element.textContent?.trim(), 50),
      href: link?.href || null,
      src: image?.src || null,
      has_link: !!link,
      has_image: !!image,
      position: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      background_color: rgbToHex(window.getComputedStyle(element).backgroundColor),
    };
  }

  /**
   * 生成元素选择器（简化版）
   */
  function generateSelector(element) {
    if (element.id) {
      return '#' + element.id;
    }

    const tagName = element.tagName.toLowerCase();

    if (element.className) {
      const classes = element.className.split(/\s+/).filter(c => c);
      if (classes.length > 0) {
        return tagName + '.' + classes.join('.');
      }
    }

    return tagName;
  }

  /**
   * 捕获视觉特征
   * @param {Element} element - 目标元素
   * @returns {Object} 视觉特征
   */
  function captureVisualFeatures(element) {
    const rect = element.getBoundingClientRect();
    const computedStyle = window.getComputedStyle(element);

    return {
      element_position: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      viewport_position: {
        x: Math.round(rect.x + window.scrollX),
        y: Math.round(rect.y + window.scrollY),
      },
      background_color: rgbToHex(computedStyle.backgroundColor),
      text_color: rgbToHex(computedStyle.color),
      font_size: parseInt(computedStyle.fontSize) || null,
      is_visible: rect.width > 0 && rect.height > 0 &&
                   computedStyle.visibility !== 'hidden' &&
                   computedStyle.display !== 'none',
      z_index: parseInt(computedStyle.zIndex) || null,
    };
  }

  /**
   * RGB 转 Hex
   */
  function rgbToHex(rgb) {
    if (!rgb || rgb === 'rgba(0, 0, 0, 0)' || rgb === 'transparent') {
      return null;
    }

    const match = rgb.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (!match) {
      return rgb;
    }

    const hex = (x) => ('0' + parseInt(x).toString(16)).slice(-2);
    return '#' + hex(match[1]) + hex(match[2]) + hex(match[3]);
  }

  /**
   * 捕获完整页面 DOM 树（简化版）
   * @returns {Object} DOM 树快照
   */
  function capturePageDOM() {
    // 简化实现：只捕获 body 的直接结构
    const body = document.body;
    if (!body) return null;

    const maxChildren = 50;
    const children = [];

    for (let i = 0; i < Math.min(body.children.length, maxChildren); i++) {
      const child = body.children[i];
      const rect = child.getBoundingClientRect();

      const node = {
        tag: child.tagName.toLowerCase(),
        id: child.id || null,
        classes: child.className ? child.className.split(/\s+/).filter(c => c) : [],
        text: truncateText(child.textContent?.trim(), 100),
        visible: rect.width > 0 && rect.height > 0,
      };

      children.push(node);
    }

    return {
      url: window.location.href,
      title: document.title,
      children: children,
    };
  }

  // ========================================================================
  // 原有功能
  // ========================================================================

  // 生成元素定位信息
  function getElementLocator(element) {
    if (!element) return null;

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

  // 发送事件到 background
  function sendEvent(eventData) {
    if (!isRecording) {
      return;
    }

    // ⭐ 新增：检查页面是否正在加载
    if (document.readyState === 'loading') {
      // console.log('[MEXEMPLAR] 页面正在加载，跳过事件');
      return;
    }

    try {
      const fullEvent = {
        ...eventData,
        timestamp: Date.now() / 1000.0,
        url: window.location.href,
        page_title: document.title  // ⭐ 新增：页面标题
      };

      // 使用异步消息发送，不等待响应（避免阻塞）
      chrome.runtime.sendMessage({
        type: 'RECORDING_EVENT',
        event: fullEvent
      });

    } catch (e) {
      console.error('[MEXEMPLAR] Error in sendEvent:', e);
    }
  }

  // 监听点击事件（使用 passive 避免阻塞页面）
  document.addEventListener('click', function(e) {
    const target = e.target;

    // 捕获增强数据
    const enhancedData = {
      action_type: 'click',
      dom_element: getElementLocator(target),
      parameters: {
        clientX: e.clientX,
        clientY: e.clientY,
        button: e.button
      },
      // 新增字段
      visual_features: captureVisualFeatures(target),
      siblings_snapshot: captureSiblings(target),
      dom_tree_snapshot: capturePageDOM(),  // 每次点击都捕获 DOM 树
    };

    sendEvent(enhancedData);
  }, true); // capture phase，但不会阻塞（sendEvent 是异步的）

  // 监听输入事件（使用 passive 避免阻塞页面）
  document.addEventListener('input', function(e) {
    const target = e.target;
    sendEvent({
      action_type: 'fill',
      dom_element: getElementLocator(target),
      parameters: {
        value: target.value || null
      }
    });
  }, true); // capture phase，但不会阻塞（sendEvent 是异步的）

  // ========================================================================
  // 低频高价值事件监听器
  // ========================================================================

  // 1. 表单提交事件
  document.addEventListener('submit', function(e) {
    const target = e.target;

    // 收集表单数据
    const formData = new FormData(target);
    const formValues = {};
    for (let [key, value] of formData.entries()) {
      formValues[key] = value;
    }

    sendEvent({
      action_type: 'submit',
      dom_element: getElementLocator(target),
      parameters: {
        form_action: target.action || null,
        form_method: target.method || null,
        form_fields: Object.keys(formValues).length,
        form_values: formValues,  // 捕获表单数据
      }
    });
  }, true);

  // 2. 双击事件
  document.addEventListener('dblclick', function(e) {
    const target = e.target;
    sendEvent({
      action_type: 'dblclick',
      dom_element: getElementLocator(target),
      parameters: {
        clientX: e.clientX,
        clientY: e.clientY,
        button: e.button
      },
      // 双击时也捕获增强数据
      visual_features: captureVisualFeatures(target),
      siblings_snapshot: captureSiblings(target),
      dom_tree_snapshot: capturePageDOM(),
    });
  }, true);

  // 3. 右键菜单事件
  document.addEventListener('contextmenu', function(e) {
    const target = e.target;
    sendEvent({
      action_type: 'contextmenu',
      dom_element: getElementLocator(target),
      parameters: {
        clientX: e.clientX,
        clientY: e.clientY,
      }
    });
  }, true);

  // 4. 表单值改变事件（针对 select, checkbox, radio）
  document.addEventListener('change', function(e) {
    const target = e.target;
    const tagName = target.tagName.toLowerCase();
    const inputType = target.type ? target.type.toLowerCase() : '';

    // 只捕获有价值的 change 事件
    if (tagName === 'select' || inputType === 'checkbox' || inputType === 'radio') {
      let value = null;
      if (tagName === 'select') {
        value = target.multiple ?
          Array.from(target.selectedOptions).map(opt => opt.value) :
          target.value;
      } else if (inputType === 'checkbox') {
        value = target.checked;
      } else if (inputType === 'radio') {
        value = target.checked ? target.value : null;
      }

      sendEvent({
        action_type: 'change',
        dom_element: getElementLocator(target),
        parameters: {
          value: value,
          tag: tagName,
          input_type: inputType,
        }
      });
    }
  }, true);

  // 5. 键盘特殊键事件（低频但高价值）
  const specialKeys = [
    'Enter', 'Escape', 'Tab',
    'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
    'Home', 'End', 'PageUp', 'PageDown',
    'Delete', 'Backspace', 'Insert'
  ];

  const modifierKeys = ['Control', 'Alt', 'Shift', 'Meta'];

  document.addEventListener('keydown', function(e) {
    const isSpecialKey = specialKeys.includes(e.key);
    const hasModifier = e.ctrlKey || e.altKey || e.metaKey;

    // 只捕获特殊键或组合键
    if (isSpecialKey || hasModifier) {
      sendEvent({
        action_type: 'keydown',
        dom_element: getElementLocator(e.target),
        parameters: {
          key: e.key,
          code: e.code,
          ctrlKey: e.ctrlKey,
          altKey: e.altKey,
          shiftKey: e.shiftKey,
          metaKey: e.metaKey,
        }
      });
    }
  }, true);

  // 6. 页面导航事件（前进/后退）
  window.addEventListener('popstate', function(e) {
    sendEvent({
      action_type: 'navigate',
      parameters: {
        url: window.location.href,
        trigger: 'popstate',
      }
    });
  });

  // ========================================================================
  // 原有功能
  // ========================================================================

  // 监听来自 background 的消息
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    // ⭐ 调试：记录所有收到的消息
    // console.log('[MEXEMPLAR] 📨 收到消息:', message.type, '完整消息:', message);

    if (message.type === 'START_RECORDING') {
      isRecording = true;
      recordingStartTime = Date.now() / 1000.0;
      recordingId = message.recording_id;

      // 保存到 storage（让新标签页也能获取状态）
      chrome.storage.local.set({
        isRecording: true,
        recordingStartTime: recordingStartTime,
        recordingId: recordingId
      });

      // ⭐ 通知 MAIN world 开始录制
      window.postMessage({
        type: 'MEXEMPLAR_SET_RECORDING',
        isRecording: true,
        recordingId: recordingId
      }, '*');

      // console.log('[ISOLATED] ✅ Recording started, 已通知 MAIN world');
      sendResponse({ success: true });
    } else if (message.type === 'STOP_RECORDING') {
      isRecording = false;

      // 清除 storage 状态
      chrome.storage.local.remove(['isRecording', 'recordingStartTime', 'recordingId']);

      // console.log('[MEXEMPLAR] ⏹️ Recording stopped');
      sendResponse({ success: true });
    }
    return true;
  });

  // ========================================================================
  // 与 MAIN world 的通信
  // ========================================================================

  // ⭐ 新增：监听来自 MAIN world 的录制状态请求
  window.addEventListener('message', (event) => {
    // 处理录制状态请求
    if (event.data.type === 'MEXEMPLAR_REQUEST_RECORDING_STATUS') {
      console.log('[ISOLATED] 📨 收到 MAIN world 的录制状态请求');
      // 立即发送当前录制状态到 MAIN world
      window.postMessage({
        type: 'MEXEMPLAR_SET_RECORDING',
        isRecording: isRecording,
        recordingId: recordingId
      }, '*');
    }

    // 处理网络请求
    if (event.data.type === 'MEXEMPLAR_NETWORK_REQUEST') {
      console.log('[ISOLATED] 📥 收到来自 MAIN world 的网络请求:', {
        url: event.data.request.url.substring(0, 100),
        hasBody: !!event.data.request.response_body,
        bodyLength: event.data.request.response_body?.length || 0
      });

      // 转发到 background（添加回调处理）
      chrome.runtime.sendMessage({
        type: 'NETWORK_REQUEST',
        recording_id: event.data.recording_id,
        request: event.data.request
      }, (response) => {
        if (chrome.runtime.lastError) {
          console.error('[ISOLATED] ❌ 发送网络请求到 Background 失败:', chrome.runtime.lastError.message);
        } else {
          console.log('[ISOLATED] ✅ 网络请求已发送到 Background:', response);
        }
      });
    }
  });

  // 当录制状态改变时，通知 MAIN world
  const notifyMainWorld = (isRecording, recordingId) => {
    window.postMessage({
      type: 'MEXEMPLAR_SET_RECORDING',
      isRecording: isRecording,
      recordingId: recordingId
    }, '*');
  };

  // 重写 chrome.runtime.sendMessage 的行为，在发送录制状态时通知 MAIN world
  const originalSendMessage = chrome.runtime.sendMessage;
  chrome.runtime.sendMessage = function(...args) {
    originalSendMessage.apply(this, args);

    // 如果是 background 的响应，不处理
    // 我们只在 START_RECORDING 消息处理中调用 notifyMainWorld
  };

  // console.log('[ISOLATED] Content script (ISOLATED world) 初始化完成');
})();

