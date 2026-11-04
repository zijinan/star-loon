// 书旗小说 开屏/广告位配置清空 (ocean.shuqireader.com getAdInfo)
// 服务端返回 data:null 时 App 视为无广告，正常进入
let body = $response.body;
try {
  const obj = JSON.parse(body);
  if (obj && obj.data) {
    obj.data = null;
    body = JSON.stringify(obj);
  }
} catch (e) {}
$done({ body });
