// Popup UI逻辑
let isRecording = false;
let recordingId = null;
let actionCount = 0;

// 更新UI状态
function updateUI() {
  const statusEl = document.getElementById('status');
  const btnStart = document.getElementById('btnStart');
  const btnStop = document.getElementById('btnStop');
  const btnExport = document.getElementById('btnExport');
  const infoEl = document.getElementById('info');
  
  if (isRecording) {
    statusEl.textContent = `录制中... (${actionCount} 个操作)`;
    statusEl.className = 'status recording';
    btnStart.disabled = true;
    btnStop.disabled = false;
    btnExport.disabled = true;
    infoEl.innerHTML = '<span class="action-count">' + actionCount + '</span> 个操作已记录';
  } else {
    statusEl.textContent = '未录制';
    statusEl.className = 'status idle';
    btnStart.disabled = false;
    btnStop.disabled = true;
    btnExport.disabled = actionCount === 0;
    if (actionCount > 0) {
      infoEl.innerHTML = `已录制 <span class="action-count">${actionCount}</span> 个操作，可以导出`;
    } else {
      infoEl.innerHTML = '';
    }
  }
}

// 获取录制状态
function getRecordingState() {
  chrome.runtime.sendMessage({ type: 'GET_RECORDING_STATE' }, (response) => {
    if (chrome.runtime.lastError) {
      console.error('Error:', chrome.runtime.lastError);
      return;
    }
    if (response) {
      isRecording = response.isRecording;
      recordingId = response.recordingId;
      actionCount = response.actionCount || 0;
      updateUI();
    }
  });
}

// 开始录制
document.getElementById('btnStart').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'START_RECORDING' }, (response) => {
    if (chrome.runtime.lastError) {
      alert('开始录制失败: ' + chrome.runtime.lastError.message);
      return;
    }
    if (response && response.success) {
      isRecording = true;
      recordingId = response.recordingId;
      actionCount = 0;
      updateUI();
    } else {
      alert('开始录制失败');
    }
  });
});

// 停止录制
document.getElementById('btnStop').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'STOP_RECORDING' }, (response) => {
    if (chrome.runtime.lastError) {
      alert('停止录制失败: ' + chrome.runtime.lastError.message);
      return;
    }
    if (response && response.success) {
      isRecording = false;
      // 获取最终的操作数量
      setTimeout(getRecordingState, 100);
    } else {
      alert('停止录制失败');
    }
  });
});

// 导出JSON
document.getElementById('btnExport').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'EXPORT_RECORDING' }, (response) => {
    if (chrome.runtime.lastError) {
      alert('导出失败: ' + chrome.runtime.lastError.message);
      return;
    }
    if (response && response.success) {
      const data = response.data;
      const jsonStr = JSON.stringify(data, null, 2);
      
      // 下载JSON文件
      const blob = new Blob([jsonStr], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `mmexemplar_recording_${data.recording_id}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      
      // 重置
      actionCount = 0;
      isRecording = false;
      recordingId = null;
      updateUI();
      
      alert(`导出成功！文件已保存为: mmexemplar_recording_${data.recording_id}.json\n\n请在Exemplar中使用导入功能加载此文件。`);
    } else {
      alert('导出失败: ' + (response.error || '未知错误'));
    }
  });
});

// 初始化
getRecordingState();
// 定期更新操作数量（每秒）
setInterval(getRecordingState, 1000);

