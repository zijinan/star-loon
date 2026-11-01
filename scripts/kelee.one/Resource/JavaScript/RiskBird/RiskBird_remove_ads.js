// 引用链接: https://kelee.one/Resource/JavaScript/RiskBird/RiskBird_remove_ads.js
// 2024-06-30 01:22:42
let data = JSON.parse($response.body);
// 删除查老板 - 热门老板
data.data && delete data.data;

$done({ body: JSON.stringify(data) });