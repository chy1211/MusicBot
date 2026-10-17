const catalog = require("../musicbot/web/i18n/zh-TW.json");
module.exports = {
 t:(key,params={})=>(catalog[key]??key).replace(/\{(p\d+)\}/g,(m,n)=>String(params[n]??m)),
 dashboardLocale:()=>"zh-TW",dashboardTimeZone:()=>"Asia/Taipei",dashboardI18nReady:Promise.resolve()
};
