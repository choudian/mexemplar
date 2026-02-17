/**
 * DOM 序列化工具
 *
 * 用于将 DOM 树序列化为 JSON 格式，以便传输和存储
 */

/**
 * 序列化 DOM 树
 * @param {Node} node - 要序列化的 DOM 节点
 * @param {Object} options - 配置选项
 * @returns {Object} 序列化后的 DOM 对象
 */
function serializeDOM(node, options = {}) {
    const {
        maxDepth = 5,              // 最大深度
        maxChildren = 100,         // 每层最多子节点数
        includeText = true,        // 是否包含文本内容
        includeAttributes = true,  // 是否包含属性
        includeStyles = false,     // 是否包含计算样式
        textMaxLength = 50,        // 文本最大长度
    } = options;

    return serializeNode(node, 0, maxDepth, maxChildren, {
        includeText,
        includeAttributes,
        includeStyles,
        textMaxLength,
    });
}

/**
 * 序列化单个节点
 */
function serializeNode(node, currentDepth, maxDepth, maxChildren, options) {
    // 递归终止条件
    if (currentDepth >= maxDepth) {
        return null;
    }

    // 跳过特定标签
    if (node.nodeType === Node.COMMENT_NODE) {
        return null;
    }

    // 处理文本节点
    if (node.nodeType === Node.TEXT_NODE) {
        if (!options.includeText || !node.textContent.trim()) {
            return null;
        }
        return {
            type: 'text',
            content: truncateText(node.textContent, options.textMaxLength),
        };
    }

    // 处理元素节点
    if (node.nodeType === Node.ELEMENT_NODE) {
        const result = {
            type: 'element',
            tag: node.tagName.toLowerCase(),
        };

        // 添加 ID
        if (node.id) {
            result.id = node.id;
        }

        // 添加类名
        if (node.className && typeof node.className === 'string') {
            result.classes = node.className.split(/\s+/).filter(c => c);
        }

        // 添加属性
        if (options.includeAttributes) {
            result.attributes = serializeAttributes(node, options);
        }

        // 添加内联样式
        if (node.style && Object.keys(node.style).length > 0) {
            result.inlineStyle = serializeInlineStyles(node.style);
        }

        // 添加文本内容
        if (options.includeText) {
            const textContent = node.textContent?.trim();
            if (textContent) {
                result.textContent = truncateText(textContent, options.textMaxLength);
            }
        }

        // 添加位置信息（如果元素可见）
        const rect = node.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
            result.position = {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
            };
        }

        // 递归处理子节点
        const children = [];
        const childNodes = Array.from(node.childNodes);

        for (let i = 0; i < Math.min(childNodes.length, maxChildren); i++) {
            const child = serializeNode(
                childNodes[i],
                currentDepth + 1,
                maxDepth,
                maxChildren,
                options
            );
            if (child) {
                children.push(child);
            }
        }

        if (children.length > 0) {
            result.children = children;
        }

        return result;
    }

    return null;
}

/**
 * 序列化元素属性
 */
function serializeAttributes(element, options) {
    const attrs = {};
    const importantAttrs = [
        'href', 'src', 'alt', 'title', 'name', 'type', 'value',
        'placeholder', 'data-testid', 'data-id', 'role', 'aria-label'
    ];

    for (const attr of importantAttrs) {
        if (element.hasAttribute(attr)) {
            attrs[attr] = element.getAttribute(attr);
        }
    }

    // 添加 data-* 属性
    for (let i = 0; i < element.attributes.length; i++) {
        const attr = element.attributes[i];
        if (attr.name.startsWith('data-') && !attrs[attr.name]) {
            attrs[attr.name] = attr.value;
        }
    }

    return Object.keys(attrs).length > 0 ? attrs : undefined;
}

/**
 * 序列化内联样式
 */
function serializeInlineStyles(style) {
    const importantStyles = [
        'display', 'position', 'visibility',
        'color', 'backgroundColor',
        'fontSize', 'fontWeight',
        'width', 'height', 'top', 'left'
    ];

    const result = {};
    for (const prop of importantStyles) {
        const value = style[prop];
        if (value) {
            result[prop] = value;
        }
    }

    return Object.keys(result).length > 0 ? result : undefined;
}

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
 * 捕获完整页面 DOM 树
 * @param {Object} options - 配置选项
 * @returns {Object} 序列化后的 DOM 树
 */
function capturePageDOM(options = {}) {
    // 克隆整个文档
    const clone = document.documentElement.cloneNode(true);

    // 移除不需要的标签
    const tagsToRemove = ['script', 'style', 'link', 'meta', 'noscript'];
    tagsToRemove.forEach(tag => {
        const elements = clone.querySelectorAll(tag);
        elements.forEach(el => el.remove());
    });

    // 序列化
    return serializeDOM(clone.body || clone, {
        maxDepth: options.maxDepth || 5,
        maxChildren: options.maxChildren || 100,
        includeText: options.includeText !== false,
        includeAttributes: options.includeAttributes !== false,
        includeStyles: false,  // 不包含计算样式（性能考虑）
        textMaxLength: 50,
    });
}

/**
 * 生成元素选择器
 * @param {Element} element - 目标元素
 * @returns {string} CSS 选择器
 */
function generateSelector(element) {
    if (element.id) {
        return `#${escapeCssId(element.id)}`;
    }

    const tagName = element.tagName.toLowerCase();

    // 检查是否有唯一的类名
    if (element.className) {
        const classes = element.className.split(/\s+/).filter(c => c);
        if (classes.length > 0) {
            const classSelector = `${tagName}.${classes.join('.')}`;
            if (document.querySelectorAll(classSelector).length === 1) {
                return classSelector;
            }
        }
    }

    // 使用 nth-child
    let parent = element.parentElement;
    if (parent) {
        const siblings = Array.from(parent.children);
        const index = siblings.indexOf(element) + 1;
        return `${generateSelector(parent)} > ${tagName}:nth-child(${index})`;
    }

    return tagName;
}

/**
 * 转义 CSS ID
 */
function escapeCssId(id) {
    return id.replace(/([^\w-])/g, '\\$1');
}

/**
 * 捕获兄弟元素
 * @param {Element} element - 目标元素
 * @returns {Object} 兄弟元素信息
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
        font_size: parseInt(computedStyle.fontSize),
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

// 导出函数（在 content script 中使用）
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        serializeDOM,
        capturePageDOM,
        captureSiblings,
        captureVisualFeatures,
        generateSelector,
    };
}
