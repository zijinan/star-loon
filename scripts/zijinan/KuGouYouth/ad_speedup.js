/*
 * 酷狗概念版 · 激励/插屏广告倒计时加速
 * 作用于 https://tmeadcomm.y.qq.com/maproxy/getAd 的 JSON 响应，
 * 仅把广告 UI 中的倒计时/浏览时长字段改小，不读取、不上传任何 Cookie/Token。
 * 注意：奖励是否发放由服务端决定，若服务端校验观看时长，可能仍需等待或奖励失败。
 */
const MS = 1000; // 毫秒字段改为 1 秒
const SEC = 1;   // 秒字段改为 1 秒
const msKeys = [
  "reward_time", "image_txt_click_reward_time", "landing_page_reward_time",
  "reward_midcard_time", "reward_reading_expo_time", "extra_reward_show_time",
  "endcard_start_time", "endcard_show_time", "midcard_start_time", "midcard_show_time",
  "ad_show_start_time", "prominent_time", "button_start_time", "button_highlight_time",
  "reward_close_button_delay_show_time", "ad_enable_close_time"
];
const secKeys = [
  "interstitial_timedown_second", "auto_close_timedown_second",
  "reduce_browsing_time", "browse_reward_time"
];
function walk(o) {
  if (Array.isArray(o)) { o.forEach(walk); return; }
  if (!o || typeof o !== "object") return;
  for (const k of Object.keys(o)) {
    const v = o[k];
    if (typeof v === "number") {
      if (msKeys.includes(k) && v > MS) o[k] = MS;
      else if (secKeys.includes(k) && v > SEC) o[k] = SEC;
    } else if (v && typeof v === "object") walk(v);
  }
  if ("enable_skip" in o) o.enable_skip = 1;
  if ("reward_skip_play" in o) o.reward_skip_play = 1;
}
let body = $response.body;
try {
  const obj = JSON.parse(body);
  walk(obj);
  body = JSON.stringify(obj);
} catch (e) {
  console.log("KuGouYouth ad_speedup: skip, " + e);
}
$done({ body });
