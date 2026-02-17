# Mexemplar Recorder 浏览器插件

## 安装说明

### 开发模式安装

1. 打开Chrome浏览器
2. 访问 `chrome://extensions/`
3. 开启"开发者模式"（右上角开关）
4. 点击"加载已解压的扩展程序"
5. 选择此目录：`src/recording/browser_extension/`

### 图标文件

插件需要以下图标文件：
- `icon16.png` - 16x16像素图标
- `icon48.png` - 48x48像素图标
- `icon128.png` - 128x128像素图标

**注意**：当前这些图标文件不存在。在加载插件前，需要：
1. 创建这些图标文件，或者
2. 临时从manifest.json中移除图标配置（插件仍可正常工作，但会显示默认图标）

## 使用说明

详细使用说明请参考：`docs/browser_extension_usage.md`

## 文件结构

- `manifest.json` - 插件配置文件
- `content_script.js` - 事件捕获脚本（注入到页面中）
- `background.js` - Background Service Worker（管理录制状态）
- `popup.html` - 插件弹窗UI
- `popup.js` - 弹窗逻辑

## 功能特性

- 捕获点击事件（click）
- 捕获输入事件（input）
- 捕获选择事件（change）
- 捕获导航事件（navigate）
- 生成元素定位信息（XPath、CSS Selector等）
- 捕获网络请求（webRequest API）
- 导出标准JSON格式

