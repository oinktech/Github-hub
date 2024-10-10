async function loadStreams() {
    const response = await fetch('/static/json/streams.json');  // 使用相對路徑
    const data = await response.json();
    const select = document.getElementById('streamSelect');
    const currentUrl = window.location.href;  // 取得當前頁面的 URL

    select.innerHTML = '';  // 清空選項

    for (const [key, value] of Object.entries(data)) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = key;

        // 比對當前 URL 與分流的 URL，若相符則設為選中狀態
        if (currentUrl.includes(value)) {
            option.selected = true;
        }

        select.appendChild(option);
    }
}
