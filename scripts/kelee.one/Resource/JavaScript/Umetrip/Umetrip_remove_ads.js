// 引用链接: https://kelee.one/Resource/JavaScript/Umetrip/Umetrip_remove_ads.js
const version = 'V1.0.1';
var ua=$request.headers.rpid||$request.headers.Rpid;ua.includes("1000002")||ua.includes("1000019")?$done({status:"HTTP/1.1 404 Not Found"}):$done({});