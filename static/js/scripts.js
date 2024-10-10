async function loadStreams() {
    const response = await fetch('/static/json/streams.json'); // 確保此路徑正確
    const data = await response.json();
    const select = document.getElementById('streamSelect');

    select.innerHTML = ''; // 清空選項

    // 獲取當前分流的 URL
    const currentStreamUrl = window.location.href; // 獲取當前網址
    let currentStreamKey = null;

    for (const [key, value] of Object.entries(data)) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = key;
        select.appendChild(option);

        // 判斷當前 URL 是否匹配分流 URL
        if (currentStreamUrl.includes(value)) {
            currentStreamKey = key; // 保存當前分流的鍵
        }
    }

    // 如果找到了當前分流，選中相應的選項
    if (currentStreamKey) {
        select.value = data[currentStreamKey];
    } else {
        select.value = ''; // 如果沒有匹配，清空選擇
    }
}

window.onload = loadStreams;
