async function loadStreams() {
    const response = await fetch('/static/json/streams.json'); // 確保此路徑正確
    const data = await response.json();
    const select = document.getElementById('streamSelect');

    select.innerHTML = ''; // 清空選項

    for (const [key, value] of Object.entries(data)) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = key;
        select.appendChild(option);
    }
}

window.onload = loadStreams;

