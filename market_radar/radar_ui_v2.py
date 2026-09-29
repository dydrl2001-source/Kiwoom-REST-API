DASHBOARD_HTML_V2 = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Market Radar V2</title>
<style>
:root{
 --bg:#f4f7fb;--panel:#ffffff;--line:#dce3ee;--txt:#152033;--muted:#6f7c90;
 --red:#e35353;--blue:#3f6fd8;--green:#15966d;--amber:#d99120;--nav:#14233a;--chip:#edf2f8;
 --purple:#7557d9;--cyan:#1693b8;--orange:#e27a2f;--mint:#2a9f88;--rose:#d85987;--indigo:#4d5bd5;
}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:13px/1.45 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR",system-ui,sans-serif}
button{font:inherit}a{color:#4267ba;text-decoration:none}.app{max-width:1500px;margin:auto;min-height:100vh;padding:14px 14px 84px}
.head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}
.brand{font-size:24px;font-weight:900;letter-spacing:-.04em}.brand small{font-size:10px;color:var(--muted);margin-left:5px}
.time{font-size:11px;color:var(--muted)}
.statusbar{display:grid;grid-template-columns:1.4fr repeat(4,1fr);gap:8px;margin-bottom:10px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 11px;min-height:67px;position:relative;overflow:hidden;box-shadow:0 4px 18px rgba(31,52,82,.035)}
.stat:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:#aab5c5}
.stat.market:before{background:var(--purple)}.stat.kiwoom:before{background:var(--blue)}.stat.material:before{background:var(--green)}.stat.turnover:before{background:var(--amber)}.stat.mimosa:before{background:var(--cyan)}
.stat .k{font-size:10px;color:var(--muted)}.stat .v{font-size:16px;font-weight:850;margin-top:3px}.stat .s{font-size:10px;color:var(--muted);margin-top:2px}
.tabs{position:sticky;top:0;z-index:20;background:rgba(244,247,251,.95);backdrop-filter:blur(8px);display:flex;gap:6px;padding:6px 0 9px;overflow:auto}
.tab{border:1px solid var(--line);background:#fff;color:var(--muted);padding:8px 13px;border-radius:999px;white-space:nowrap;font-weight:700;cursor:pointer}
.tab.active{background:var(--nav);color:#fff;border-color:var(--nav);box-shadow:0 4px 12px rgba(20,35,58,.14)}
.tab[data-view="index"].active{background:var(--purple);border-color:var(--purple)}
.tab[data-view="query"].active{background:var(--blue);border-color:var(--blue)}
.tab[data-view="sector"].active{background:#6b5ec9;border-color:#6b5ec9}
.tab[data-view="trade"].active{background:var(--orange);border-color:var(--orange)}
.tab[data-view="material"].active{background:var(--green);border-color:var(--green)}
.tab[data-view="research"].active{background:var(--indigo);border-color:var(--indigo)}
.tab[data-view="brokerage"].active{background:#111827;border-color:#111827}
.tab[data-view="mimosa"].active{background:var(--cyan);border-color:var(--cyan)}
.view{display:none}.view.active{display:block}.section-title{display:flex;align-items:end;justify-content:space-between;margin:14px 2px 7px}.section-title h2{font-size:15px;margin:0}.section-title span{font-size:10px;color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}.pad{padding:12px}
.analysis{display:grid;grid-template-columns:1.3fr .7fr;gap:8px}.analysis-main{font-size:14px}.analysis-line{padding:7px 0;border-bottom:1px solid #eef2f7}.analysis-line:last-child{border:0}
.legend{display:flex;flex-wrap:wrap;gap:5px}.pill{display:inline-flex;align-items:center;gap:4px;padding:3px 7px;border-radius:999px;background:var(--chip);font-size:10px;color:#4d5d73}
.good{color:var(--green)}.bad{color:var(--blue)}.hot{color:var(--red)}.warn{color:var(--amber)}.muted{color:var(--muted)}
.sector-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;align-items:start}.sector-card{background:#fff;border:1px solid var(--line);border-top:4px solid #7b67da;border-radius:11px;overflow:hidden;box-shadow:0 3px 14px rgba(42,53,79,.03)}
.sector-head{display:flex;justify-content:space-between;align-items:flex-start;gap:8px;padding:10px;border-bottom:1px solid #edf1f6}.sector-head strong{font-size:14px}.sector-meta{font-size:10px;color:var(--muted)}.sector-money{font-size:11px;font-weight:850;margin-top:3px}.sector-reason{padding:8px 10px;background:#f8fafc;border-top:1px solid #edf1f6;font-size:10px;line-height:1.55;color:#4d5d73}.sector-reason b{color:#2a3850}.sector-reason.supported{background:#eef9f5}.sector-reason.partial{background:#fff8e9}.sector-reason.unconfirmed{background:#f5f7fa}.sector-evidence{display:flex;gap:4px;flex-wrap:wrap;margin-top:5px}.sector-evidence-lines{margin-top:5px;padding-top:4px;border-top:1px dashed #dfe6ef}.sector-evidence-line{margin:3px 0;color:#52627a}.sector-evidence-line b{color:#2d3c55}
.stock-list{display:grid;grid-template-columns:1fr 1fr;align-items:start}.stock-mini{padding:8px 9px;border-right:1px solid #f0f3f7;border-bottom:1px solid #f0f3f7;min-height:88px}.stock-mini:nth-child(2n){border-right:0}
.stock-mini .name{font-weight:850;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.stock-mini .num{display:flex;justify-content:space-between;margin-top:4px;font-size:11px}.stock-money{font-weight:800;margin-top:4px}.stock-burst{font-size:9px;color:#697992;margin-top:2px}.moneybar{height:3px;background:#edf1f7;border-radius:99px;overflow:hidden;margin-top:5px}.moneybar i{display:block;height:100%;background:#7184d8;border-radius:99px}.rank-badge{font-size:9px;color:#fff;background:#7b8799;border-radius:4px;padding:1px 4px}
.sector-chip{display:inline-flex;align-items:center;gap:5px;border-radius:999px;padding:4px 8px;font-size:10px;font-weight:800;white-space:nowrap}.sector-chip i{width:7px;height:7px;border-radius:50%;display:block}.surge-sector-bar{display:flex;gap:6px;flex-wrap:wrap;padding:9px 10px;background:#fff;border:1px solid var(--line);border-radius:11px;margin-bottom:7px}.surge-sector-bar .sector-chip{cursor:default}
.sector-card.sc0{border-top-color:#5d6fd7}.sector-card.sc1{border-top-color:#1d9b83}.sector-card.sc2{border-top-color:#dd8b35}.sector-card.sc3{border-top-color:#b85d8f}.sector-card.sc4{border-top-color:#3f8fc0}.sector-card.sc5{border-top-color:#8a62c8}.sector-card.sc6{border-top-color:#6b8e45}.sector-card.sc7{border-top-color:#c25a52}
.sector-chip.sc0{background:#e9edff;color:#4053a5}.sector-chip.sc1{background:#e2f5ef;color:#116b5a}.sector-chip.sc2{background:#fff0df;color:#915515}.sector-chip.sc3{background:#f9e8f1;color:#91466f}.sector-chip.sc4{background:#e5f3fa;color:#2f7295}.sector-chip.sc5{background:#f0e9fa;color:#684595}.sector-chip.sc6{background:#edf4e4;color:#567431}.sector-chip.sc7{background:#fbe9e7;color:#92453f}
.sector-chip.sc0 i{background:#5d6fd7}.sector-chip.sc1 i{background:#1d9b83}.sector-chip.sc2 i{background:#dd8b35}.sector-chip.sc3 i{background:#b85d8f}.sector-chip.sc4 i{background:#3f8fc0}.sector-chip.sc5 i{background:#8a62c8}.sector-chip.sc6 i{background:#6b8e45}.sector-chip.sc7 i{background:#c25a52}
.sector-pulse{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin-bottom:9px}.sector-pulse-card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:9px 10px;position:relative;overflow:hidden}.sector-pulse-card:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:#7b8799}.sector-pulse-card.sc0:before{background:#5d6fd7}.sector-pulse-card.sc1:before{background:#1d9b83}.sector-pulse-card.sc2:before{background:#dd8b35}.sector-pulse-card.sc3:before{background:#b85d8f}.sector-pulse-card.sc4:before{background:#3f8fc0}.sector-pulse-card.sc5:before{background:#8a62c8}.sector-pulse-card.sc6:before{background:#6b8e45}.sector-pulse-card.sc7:before{background:#c25a52}.sector-pulse-card .sp-name{font-weight:850;font-size:12px}.sector-pulse-card .sp-count{font-size:19px;font-weight:900;margin-top:2px}.sector-pulse-card .sp-money{font-size:10px;color:var(--muted);margin-top:2px}.sector-pulse-card .sp-reason{font-size:9px;color:#52627a;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.theme-strength{margin-top:6px}.theme-strength-top{display:flex;justify-content:space-between;align-items:center;font-size:10px}.theme-strength-top b{font-size:12px}.theme-strength-bar{height:6px;background:#edf1f7;border-radius:99px;overflow:hidden;margin-top:4px}.theme-strength-bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#7b8ce0,#19a287)}.theme-components{font-size:9px;color:#718098;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.signal-badge{display:inline-flex;align-items:center;gap:4px;padding:2px 6px;border-radius:999px;font-size:9px;font-weight:850;margin-top:3px}.signal-top{background:#ffeded;color:#a73f46}.signal-bottom{background:#e8f1ff;color:#315fa7}.signal-badge small{font-size:8px;font-weight:700;opacity:.8}
.material-tag{display:inline-flex;align-items:center;padding:3px 7px;border-radius:999px;font-size:9px;font-weight:850;white-space:nowrap}.mt-contract{background:#e8efff;color:#365ea7}.mt-earnings{background:#e6f6ed;color:#197451}.mt-product{background:#fff0df;color:#9a5d18}.mt-policy{background:#f0e9fb;color:#704da3}.mt-clinical{background:#ffe8ec;color:#a94055}.mt-capital{background:#e9f4fa;color:#37779a}.mt-industry{background:#f3eafe;color:#7a52a8}.mt-ma{background:#efe9e4;color:#775441}.mt-unknown{background:#eef1f5;color:#647386}
.rank-move{display:inline-flex;align-items:center;justify-content:center;min-width:30px;padding:2px 5px;border-radius:6px;font-size:9px;font-weight:900;margin-top:3px}.rank-up{background:#ffeded;color:#b3434a}.rank-down{background:#e9f0ff;color:#3c67ad}.rank-new{background:#fff1db;color:#93600e}.rank-re{background:#e7f5ef;color:#197059}.rank-flat{background:#eef1f5;color:#748196}.rank-history{font-size:9px;color:#728098;line-height:1.5;margin-top:3px}
.os-mini{margin-top:6px;padding:6px 7px;border-radius:7px;background:#f3f4ff;border:1px solid #e0e3fb;font-size:10px;line-height:1.45;color:#4a5276}.os-mini b{color:#4d5bd5}.os-links{display:flex;gap:6px;flex-wrap:wrap;margin-top:4px}.os-links a{font-size:9px;font-weight:800}.material-cell{max-width:430px;white-space:normal;text-align:left}.material-main{font-weight:750;line-height:1.45;margin-top:4px}.material-meta{display:flex;gap:4px;flex-wrap:wrap;align-items:center}
.home-brief{display:flex;align-items:center;gap:8px;flex-wrap:wrap;background:linear-gradient(90deg,#17253c,#263b5d);color:#fff;border-radius:11px;padding:10px 12px;margin-top:8px;box-shadow:0 4px 14px rgba(20,35,58,.12)}.home-brief b{font-size:13px}.home-brief span{font-size:10px;color:#dce6f7}
.home-market-tools{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;margin-top:7px}.home-market-tools .legend{flex:1}.market-detail{margin:0;background:#fff;border:1px solid var(--line);border-radius:9px;padding:7px 9px;min-width:150px}.market-detail summary{font-weight:800;font-size:10px;color:#596a83}.market-detail .analysis-line{font-size:10px;padding:5px 0}.home-candidates{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px}.home-candidate{background:#fff;border:1px solid var(--line);border-radius:10px;padding:9px;border-top:3px solid #7081da;min-width:0}.home-candidate .hc-top{display:flex;justify-content:space-between;gap:7px;align-items:flex-start}.home-candidate .hc-name{font-weight:900;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.home-candidate .hc-score{font-size:20px;font-weight:900}.home-candidate .hc-meta{font-size:9px;color:var(--muted);margin-top:3px}.home-candidate .hc-money{font-size:10px;font-weight:800;margin-top:6px}.home-candidate .hc-tags{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}
.paper-lab{background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}.paper-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:11px 12px;border-bottom:1px solid #edf1f6}.paper-head b{font-size:13px}.paper-badge{display:inline-flex;align-items:center;padding:3px 7px;border-radius:999px;background:#eef1f5;color:#647386;font-size:9px;font-weight:850}.paper-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;border-bottom:1px solid #edf1f6}.paper-kpi{padding:10px 12px;border-right:1px solid #edf1f6}.paper-kpi:last-child{border-right:0}.paper-kpi .pk{font-size:9px;color:var(--muted)}.paper-kpi .pv{font-size:18px;font-weight:900;margin-top:2px}.paper-open-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;padding:10px}.paper-position{border:1px solid #dce4ef;border-radius:9px;padding:9px;border-top:3px solid #6779d7;min-width:0}.paper-position .pp-name{font-size:12px;font-weight:900;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.paper-position .pp-ret{font-size:20px;font-weight:900}.paper-position .pp-meta{font-size:9px;color:var(--muted);line-height:1.55}.paper-position .pp-prices{font-size:10px;font-weight:800;margin-top:6px}.paper-path{display:flex;gap:5px;flex-wrap:wrap;margin-top:6px}.paper-reason{font-size:9px;color:#607086;line-height:1.5;margin-top:6px}.paper-closed{border-top:1px solid #edf1f6}.paper-closed summary{padding:9px 12px;font-size:10px;font-weight:850;color:#596a83}.paper-table-wrap{overflow:auto;max-height:260px}.paper-table{width:100%;border-collapse:collapse;min-width:780px;font-size:9px}.paper-table th,.paper-table td{padding:7px 8px;border-top:1px solid #edf1f6;text-align:right;white-space:nowrap}.paper-table th:first-child,.paper-table td:first-child{text-align:left}.paper-table th{background:#f8fafc;color:var(--muted)}
.paper-feedback{margin-top:8px;background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}.pf-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:10px 12px;border-bottom:1px solid #edf1f6}.pf-head b{font-size:12px}.pf-state{display:inline-flex;padding:3px 7px;border-radius:999px;font-size:9px;font-weight:900}.pf-sample{background:#eef1f5;color:#667487}.pf-keep{background:#e7f5ef;color:#176f55}.pf-review{background:#fff0df;color:#965d18}.pf-overall{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));border-bottom:1px solid #edf1f6}.pf-kpi{padding:9px 10px;border-right:1px solid #edf1f6}.pf-kpi:last-child{border-right:0}.pf-kpi .k{font-size:8px;color:var(--muted)}.pf-kpi .v{font-size:14px;font-weight:900;margin-top:2px}.pf-grid{display:grid;grid-template-columns:1.2fr 1fr;gap:10px;padding:10px}.pf-box{border:1px solid #e3e9f1;border-radius:9px;overflow:hidden}.pf-box-head{padding:7px 9px;background:#f8fafc;font-size:10px;font-weight:850;color:#596a83}.pf-check{padding:8px 9px;border-top:1px solid #eef2f7}.pf-check:first-of-type{border-top:0}.pf-check-title{display:flex;justify-content:space-between;gap:8px;align-items:center;font-size:10px;font-weight:850}.pf-check p{font-size:9px;line-height:1.5;color:#66758a;margin:4px 0 0}.pf-type{display:grid;grid-template-columns:minmax(0,1fr) 34px 58px 58px;gap:6px;align-items:center;padding:7px 9px;border-top:1px solid #eef2f7;font-size:9px}.pf-type:first-of-type{border-top:0}.pf-type b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pf-band{font-size:9px;padding:6px 9px;border-top:1px solid #eef2f7;display:flex;justify-content:space-between;gap:8px}.pf-note{padding:8px 11px;border-top:1px solid #edf1f6;font-size:9px;color:#778499}


.material-legend{display:flex;gap:5px;flex-wrap:wrap;align-items:center;margin:5px 0 7px}.material-legend .legend-label{font-size:9px;color:var(--muted);font-weight:800;margin-right:2px}
.leader-desk{display:grid;grid-template-columns:1.02fr 1.28fr 1fr;gap:10px;align-items:start;margin-bottom:10px}.leader-panel{background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden;box-shadow:0 4px 18px rgba(31,52,82,.035)}.leader-panel-head{display:flex;justify-content:space-between;align-items:end;gap:8px;padding:10px 11px;border-bottom:1px solid #edf1f6}.leader-panel-head b{font-size:13px}.leader-panel-head span{font-size:9px;color:var(--muted)}.leader-panel-body{padding:8px}
.lead-sector{border:1px solid #e1e7f0;border-left:4px solid #7b67da;border-radius:9px;margin-bottom:7px;overflow:hidden}
.lead-sector.sc0{border-left-color:#5d6fd7}.lead-sector.sc1{border-left-color:#1d9b83}.lead-sector.sc2{border-left-color:#dd8b35}.lead-sector.sc3{border-left-color:#b85d8f}.lead-sector.sc4{border-left-color:#3f8fc0}.lead-sector.sc5{border-left-color:#8a62c8}.lead-sector.sc6{border-left-color:#6b8e45}.lead-sector.sc7{border-left-color:#c25a52}
.lead-sector:last-child{margin-bottom:0}.lead-sector-head{display:flex;justify-content:space-between;gap:8px;padding:8px;background:#fbfcfe}.lead-sector-head b{font-size:12px}.lead-sector-head .ls-meta{font-size:9px;color:var(--muted);margin-top:2px}.lead-sector-stocks{border-top:1px solid #eef2f7}.lead-sector-reason{padding:6px 8px;background:#f8fafc;border-top:1px solid #eef2f7;font-size:9px;line-height:1.45;color:#5b6a80}.lead-sector-strength{font-size:9px;color:#6d7a8e;margin-top:2px}.lead-stock{display:grid;grid-template-columns:minmax(0,1fr) 74px 54px 72px;gap:7px;align-items:center;padding:6px 8px;border-top:1px solid #f1f4f8;font-size:10px}.lead-stock:first-child{border-top:0}.lead-stock b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.lead-stock .ls-change{text-align:right;font-weight:800}.lead-stock .ls-money{text-align:right;color:#4e5d73;font-weight:750}
.strong-head,.strong-row{display:grid;grid-template-columns:32px minmax(120px,1.15fr) 88px 64px 88px;gap:6px;align-items:center}.strong-row{border-left:3px solid transparent}.strong-row.sc0{border-left-color:#5d6fd7}.strong-row.sc1{border-left-color:#1d9b83}.strong-row.sc2{border-left-color:#dd8b35}.strong-row.sc3{border-left-color:#b85d8f}.strong-row.sc4{border-left-color:#3f8fc0}.strong-row.sc5{border-left-color:#8a62c8}.strong-row.sc6{border-left-color:#6b8e45}.strong-row.sc7{border-left-color:#c25a52}.strong-head{padding:5px 6px;color:var(--muted);font-size:9px;border-bottom:1px solid #eef2f7}.strong-row{padding:7px 6px;border-bottom:1px solid #eef2f7;font-size:10px}.strong-row:last-child{border-bottom:0}.strong-row .sr-rank{font-weight:900;color:#59677b}.strong-row .sr-name{font-weight:850;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.strong-row .sr-price{text-align:right;font-weight:800}.strong-row .sr-change{text-align:right;font-weight:850}.strong-row .sr-money{text-align:right;color:#53627a}.strong-theme{font-size:8px;color:#718096;font-weight:700;margin-left:4px}
.calendar-wrap{overflow:auto}.leader-calendar{min-width:520px;display:grid;grid-template-columns:repeat(5,1fr);border-left:1px solid #eef2f7;border-top:1px solid #eef2f7}.cal-head{padding:5px;text-align:center;font-size:9px;font-weight:850;color:#738096;background:#f8fafc;border-right:1px solid #eef2f7;border-bottom:1px solid #eef2f7}.cal-cell{min-height:76px;padding:5px;border-right:1px solid #eef2f7;border-bottom:1px solid #eef2f7;background:#fff}.cal-cell.future{background:#fafbfd;color:#a5aebb}.cal-date{font-size:9px;color:#7e8a9d;margin-bottom:4px}.cal-theme{display:block;font-size:9px;line-height:1.35;font-weight:800;margin:2px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cal-theme.sc0{color:#4053a5}.cal-theme.sc1{color:#116b5a}.cal-theme.sc2{color:#915515}.cal-theme.sc3{color:#91466f}.cal-theme.sc4{color:#2f7295}.cal-theme.sc5{color:#684595}.cal-theme.sc6{color:#567431}.cal-theme.sc7{color:#92453f}
.calendar-note{font-size:9px;color:#7a8799;padding:7px 1px 0}




.surge-row td:first-child{position:relative;padding-left:13px}.surge-row.sc0 td:first-child:before,.surge-row.sc1 td:first-child:before,.surge-row.sc2 td:first-child:before,.surge-row.sc3 td:first-child:before,.surge-row.sc4 td:first-child:before,.surge-row.sc5 td:first-child:before,.surge-row.sc6 td:first-child:before,.surge-row.sc7 td:first-child:before{content:"";position:absolute;left:0;top:4px;bottom:4px;width:4px;border-radius:4px}.surge-row.sc0 td:first-child:before{background:#5d6fd7}.surge-row.sc1 td:first-child:before{background:#1d9b83}.surge-row.sc2 td:first-child:before{background:#dd8b35}.surge-row.sc3 td:first-child:before{background:#b85d8f}.surge-row.sc4 td:first-child:before{background:#3f8fc0}.surge-row.sc5 td:first-child:before{background:#8a62c8}.surge-row.sc6 td:first-child:before{background:#6b8e45}.surge-row.sc7 td:first-child:before{background:#c25a52}

.tblwrap{overflow:auto;max-height:660px}.tbl{width:100%;border-collapse:collapse;min-width:980px}.tbl th,.tbl td{padding:8px 8px;border-bottom:1px solid #edf1f6;text-align:right;vertical-align:middle;white-space:nowrap}.tbl th{position:sticky;top:0;background:#f8fafc;color:var(--muted);font-size:10px;z-index:2}.tbl .left{text-align:left}.tbl .wrap{white-space:normal;min-width:220px;text-align:left}
.stockname{font-weight:850}.sub{font-size:10px;color:var(--muted)}
.material-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.research-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.research-card{background:#fff;border:1px solid var(--line);border-left:4px solid #9aa8bb;border-radius:11px;padding:11px;box-shadow:0 3px 14px rgba(42,53,79,.03)}
.research-card.p-high{border-left-color:var(--red)}.research-card.p-mid{border-left-color:var(--amber)}.research-card.p-low{border-left-color:var(--blue)}
.priority{font-size:18px;font-weight:900}.deep{color:#9b5b00;background:#fff2dc}
.deep-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.deep-card{background:#fff;border:1px solid var(--line);border-left:5px solid var(--indigo);border-radius:13px;padding:13px;box-shadow:0 6px 22px rgba(55,67,120,.06)}
.deep-head{display:flex;justify-content:space-between;gap:10px}.confidence{display:inline-flex;align-items:center;justify-content:center;min-width:48px;height:48px;border-radius:50%;background:#eef0ff;color:var(--indigo);font-weight:900;font-size:15px}
.deep-row{display:grid;grid-template-columns:105px 1fr;gap:8px;padding:7px 0;border-top:1px solid #edf1f6}.deep-row:first-of-type{border-top:0}.deep-key{font-size:10px;color:var(--muted);font-weight:800}.risk-pill{background:#fff0f1;color:#b43c4c}.agent-pill{background:#edf4ff;color:#365ea7}.material-card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:11px}
.material-top{display:flex;justify-content:space-between;gap:6px}.material-card h3{font-size:14px;margin:0}.material-summary{font-weight:750;margin:8px 0 5px;line-height:1.5}.material-why{font-size:11px;color:#516078;background:#f6f8fb;padding:7px;border-radius:7px}
details{margin-top:7px}summary{cursor:pointer;color:#526785;font-size:11px}.evidence{border-top:1px solid #edf1f6;margin-top:7px;padding-top:7px;font-size:11px}.evidence p{margin:4px 0}.links{display:flex;gap:7px;flex-wrap:wrap}
.mimosa-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.index-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.chart-card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:10px}.chart-title{display:flex;justify-content:space-between;align-items:end;margin-bottom:6px}.chart-title b{font-size:14px}.svgchart{width:100%;height:210px;display:block}.strategy-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.strategy-card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:10px}.strategy-card h3{font-size:13px;margin:0}.strategy-score{font-weight:900;font-size:16px}.strategy-note{font-size:10px;color:var(--muted);margin-top:6px}.m-card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:10px}.m-head{display:flex;justify-content:space-between}.m-state{font-size:13px;font-weight:900;margin-top:6px}.score{font-weight:900}.reason{font-size:10px;color:var(--muted);margin-top:5px}.fb{display:flex;gap:5px;margin-top:8px}.fb button{border:1px solid var(--line);background:#fff;border-radius:7px;padding:4px 7px;font-size:10px;color:#5d6b7f;cursor:pointer}.fb button:hover{background:#f3f6fa}.fb .sent{background:#eaf6f1;color:#187a59}
.broker-hero{background:linear-gradient(135deg,#101827,#233653);color:#fff;border-radius:16px;padding:20px;display:grid;grid-template-columns:1.4fr .6fr;gap:16px;box-shadow:0 10px 30px rgba(17,24,39,.12)}
.broker-eyebrow{font-size:10px;font-weight:900;letter-spacing:.12em;color:#9ec5ff}.broker-hero h2{font-size:26px;line-height:1.25;margin:5px 0 8px;letter-spacing:-.04em}.broker-hero p{margin:0;color:#d7e0ec;max-width:780px}.broker-mode{display:flex;flex-direction:column;justify-content:center;align-items:flex-end;text-align:right}.broker-mode strong{font-size:24px}.broker-mode span{font-size:10px;color:#b8c5d8}
.broker-cycle{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:7px;margin-top:9px}.broker-step{background:#fff;border:1px solid var(--line);border-radius:10px;padding:9px}.broker-step b{display:block;font-size:11px}.broker-step span{font-size:9px;color:var(--muted)}.broker-step i{font-style:normal;font-size:9px;font-weight:900;color:#5d6fd7}
.broker-desks{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.broker-desk{background:#fff;border:1px solid var(--line);border-radius:11px;padding:10px;border-left:4px solid #7184d8}.broker-desk b{font-size:12px}.broker-desk p{font-size:9px;color:#66758a;margin:4px 0 0;line-height:1.55}
.broker-registry{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.broker-reg{background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px}.broker-reg .br-v{font-size:21px;font-weight:900}.broker-reg .br-k{font-size:9px;color:var(--muted)}
.broker-candidates{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.broker-card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:11px;border-top:4px solid #97a4b8}.broker-card.entry{border-top-color:#15966d}.broker-card.ready{border-top-color:#3f6fd8}.broker-card.watch{border-top-color:#d99120}.broker-card.blocked{border-top-color:#e35353}.broker-top{display:flex;justify-content:space-between;gap:8px}.broker-name{font-size:14px;font-weight:900}.broker-state{display:inline-flex;padding:3px 7px;border-radius:999px;background:#eef1f5;font-size:9px;font-weight:900}.broker-conv{font-size:24px;font-weight:900;text-align:right}.broker-strategy{margin-top:7px;padding:7px 8px;border-radius:8px;background:#f6f8fb;font-size:10px}.broker-deskline{display:grid;grid-template-columns:72px 1fr 34px;gap:6px;align-items:center;margin-top:5px;font-size:9px}.broker-bar{height:5px;background:#edf1f6;border-radius:99px;overflow:hidden}.broker-bar i{display:block;height:100%;background:#7184d8;border-radius:99px}.broker-block{margin-top:7px;padding:7px 8px;background:#fff0f1;border-radius:8px;color:#9c3d49;font-size:9px;line-height:1.5}.broker-foot{margin-top:7px;font-size:9px;color:#748196}
.broker-principle{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px;display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.broker-principle div{border-left:3px solid #dbe3ee;padding-left:9px}.broker-principle b{display:block;font-size:11px}.broker-principle span{font-size:9px;color:var(--muted)}
.broker-brief{display:grid;grid-template-columns:1.2fr repeat(3,.7fr);gap:8px}.brief-card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:11px}.brief-card.main{background:linear-gradient(135deg,#f7f9fd,#eef3fb)}.brief-k{font-size:9px;color:var(--muted);font-weight:800}.brief-v{font-size:18px;font-weight:900;margin-top:2px}.brief-list{display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}
.strategy-perf{background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}.strategy-perf table{width:100%;border-collapse:collapse;min-width:850px}.strategy-perf th,.strategy-perf td{padding:8px;border-bottom:1px solid #edf1f6;text-align:right;font-size:9px}.strategy-perf th{background:#f8fafc;color:var(--muted);position:sticky;top:0}.strategy-perf th:first-child,.strategy-perf td:first-child{text-align:left}.sp-state{display:inline-flex;padding:2px 6px;border-radius:999px;background:#eef1f5;font-size:8px;font-weight:900}
.lifecycle-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:10px;border-top:1px solid #edf1f6}.lifecycle-card{border:1px solid #e2e8f0;border-radius:9px;padding:9px;background:#fbfcfe}.lifecycle-card.promote{border-color:#9ed8c6;background:#f0faf6}.lifecycle-card.demote,.lifecycle-card.rework{border-color:#f0c6ca;background:#fff6f7}.lifecycle-card .lc-top{display:flex;justify-content:space-between;gap:6px}.lifecycle-card .lc-name{font-size:10px;font-weight:900}.lifecycle-card .lc-label{font-size:8px;font-weight:900}.lifecycle-card .lc-meta{font-size:8px;color:var(--muted);margin-top:4px}.context-wrap{border-top:1px solid #edf1f6}.context-head{padding:8px 10px;font-size:10px;font-weight:900;background:#f8fafc}.context-table{width:100%;border-collapse:collapse;min-width:860px}.context-table th,.context-table td{padding:7px 8px;border-top:1px solid #edf1f6;font-size:8px;text-align:right}.context-table th:first-child,.context-table td:first-child{text-align:left}.context-table th{color:var(--muted);background:#fbfcfe}
.capacity-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;padding:10px}.capacity-card{border:1px solid #e2e8f0;border-radius:10px;padding:10px;background:#fbfcfe}.capacity-card.supported{border-color:#9ed8c6;background:#f0faf6}.capacity-card.blocked{border-color:#f0c6ca;background:#fff6f7}.capacity-card .cap-top{display:flex;justify-content:space-between;gap:8px}.capacity-card .cap-name{font-size:10px;font-weight:900}.capacity-card .cap-val{font-size:18px;font-weight:900;margin-top:4px}.capacity-card .cap-meta{font-size:8px;color:var(--muted);margin-top:4px}.capacity-gate{padding:9px 10px;border-bottom:1px solid #edf1f6;background:#f8fafc;font-size:9px}
.allocation-lab{background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}.allocation-summary{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));border-bottom:1px solid #edf1f6}.allocation-kpi{padding:10px;border-right:1px solid #edf1f6}.allocation-kpi:last-child{border-right:0}.allocation-kpi .ak{font-size:8px;color:var(--muted)}.allocation-kpi .av{font-size:17px;font-weight:900;margin-top:2px}.allocation-table{width:100%;border-collapse:collapse;min-width:1180px}.allocation-table th,.allocation-table td{padding:7px 8px;border-top:1px solid #edf1f6;font-size:8px;text-align:right;white-space:nowrap}.allocation-table th{background:#f8fafc;color:var(--muted)}.allocation-table th:first-child,.allocation-table td:first-child{text-align:left}.allocation-note{padding:8px 10px;border-top:1px solid #edf1f6;font-size:9px;color:#6d7a8e}.allocation-rejected{padding:8px 10px;border-top:1px solid #edf1f6;background:#fbfcfe}.allocation-rejected summary{font-size:9px;font-weight:900}.allocation-reason{display:flex;justify-content:space-between;gap:8px;padding:5px 0;border-top:1px solid #eef2f7;font-size:8px}.allocation-reason:first-of-type{border-top:0}
.shadow-lab{background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}.shadow-summary{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));border-bottom:1px solid #edf1f6}.shadow-kpi{padding:10px;border-right:1px solid #edf1f6}.shadow-kpi:last-child{border-right:0}.shadow-kpi .sk{font-size:8px;color:var(--muted)}.shadow-kpi .sv{font-size:17px;font-weight:900;margin-top:2px}.shadow-table{width:100%;border-collapse:collapse;min-width:1150px}.shadow-table th,.shadow-table td{padding:7px 8px;border-top:1px solid #edf1f6;font-size:8px;text-align:right;white-space:nowrap}.shadow-table th{background:#f8fafc;color:var(--muted)}.shadow-table th:first-child,.shadow-table td:first-child{text-align:left}.shadow-note{padding:8px 10px;border-top:1px solid #edf1f6;font-size:9px;color:#6d7a8e}.shadow-status{display:inline-flex;padding:2px 6px;border-radius:999px;background:#eef1f5;font-size:8px;font-weight:900}.shadow-status.closed{background:#e7f5ef;color:#176f55}.shadow-status.partial{background:#fff0df;color:#965d18}.shadow-status.rejected{background:#fff0f1;color:#a5404d}
.daily-review{display:grid;grid-template-columns:1.1fr .9fr;gap:8px}.review-box{background:#fff;border:1px solid var(--line);border-radius:11px;padding:11px}.review-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-top:8px}.review-kpi{background:#f8fafc;border-radius:8px;padding:8px}.review-kpi .rk{font-size:8px;color:var(--muted)}.review-kpi .rv{font-size:16px;font-weight:900}.review-lines{margin-top:7px}.review-line{display:flex;justify-content:space-between;gap:8px;border-top:1px solid #eef2f7;padding:6px 0;font-size:9px}.review-line:first-child{border-top:0}
.bottom{display:none}
@media(max-width:1100px){.broker-brief{grid-template-columns:1fr 1fr}.daily-review{grid-template-columns:1fr}.shadow-summary,.allocation-summary{grid-template-columns:repeat(3,1fr)}.lifecycle-grid,.capacity-grid{grid-template-columns:1fr 1fr}.broker-cycle{grid-template-columns:repeat(3,1fr)}.broker-desks{grid-template-columns:repeat(2,1fr)}.leader-desk{grid-template-columns:1fr 1fr}.leader-desk .leader-panel:last-child{grid-column:1/-1}.home-candidates{grid-template-columns:repeat(3,minmax(0,1fr))}.paper-open-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.pf-grid{grid-template-columns:1fr}.sector-grid{grid-template-columns:repeat(2,1fr)}.material-grid,.research-grid,.deep-grid{grid-template-columns:repeat(2,1fr)}.mimosa-grid{grid-template-columns:repeat(2,1fr)}.strategy-grid{grid-template-columns:repeat(2,1fr)}.index-grid{grid-template-columns:1fr}.statusbar{grid-template-columns:1fr 1fr 1fr}.analysis{grid-template-columns:1fr}}
@media(max-width:700px){
 .app{padding:10px 8px 82px}.head{margin-bottom:6px}.brand{font-size:20px}.statusbar{grid-template-columns:1fr 1fr;gap:6px}.stat{min-height:61px;padding:8px}
 .statusbar .stat:first-child{grid-column:1/-1}.tabs{display:none}.leader-desk{grid-template-columns:1fr}.leader-desk .leader-panel:last-child{grid-column:auto}.home-market-tools{display:block}.market-detail{margin-top:6px}.home-candidates{grid-template-columns:1fr}.paper-summary{grid-template-columns:1fr 1fr}.paper-open-grid{grid-template-columns:1fr}.pf-overall{grid-template-columns:1fr 1fr}.pf-grid{grid-template-columns:1fr}.sector-grid{grid-template-columns:1fr;gap:7px}.stock-list{grid-template-columns:1fr 1fr}.stock-mini{border-right:1px solid #f0f3f7}
 .broker-hero{grid-template-columns:1fr}.broker-mode{align-items:flex-start;text-align:left}.broker-cycle,.broker-desks,.broker-registry,.broker-candidates,.broker-principle,.broker-brief,.daily-review,.review-grid,.lifecycle-grid,.capacity-grid,.shadow-summary,.allocation-summary{grid-template-columns:1fr}.material-grid,.research-grid,.deep-grid,.mimosa-grid,.strategy-grid{grid-template-columns:1fr}.sector-pulse{grid-template-columns:1fr 1fr}.section-title{margin-top:10px}.bottom{display:flex;position:fixed;bottom:0;left:0;right:0;z-index:40;background:#fff;border-top:1px solid var(--line);padding:5px 4px calc(5px + env(safe-area-inset-bottom));justify-content:space-around}
 .bottom button{border:0;background:transparent;color:#78869b;font-size:9px;display:flex;flex-direction:column;align-items:center;gap:2px;padding:4px 5px}.bottom button.active{color:#1c2b45;font-weight:900}.bottom b{font-size:16px;line-height:1}
}
</style></head>
<body><div class="app">
<div class="head"><div><span class="brand">MARKET RADAR <small>V2</small></span></div><div class="time" id="stamp">연결 중</div></div>

<div class="statusbar">
 <div class="stat market"><div class="k">오늘 장</div><div class="v" id="regime">대기</div><div class="s" id="regimeSub">시장 데이터 확인 중</div></div>
 <div class="stat kiwoom"><div class="k">실시간 데이터</div><div class="v" id="kiwoom">-</div><div class="s" id="kiwoomSub"></div></div>
 <div class="stat material"><div class="k">재료 / 뉴스</div><div class="v" id="newsStatus">-</div><div class="s" id="newsSub"></div></div>
 <div class="stat turnover"><div class="k">조회 Top20 교체율</div><div class="v" id="turnover">-</div><div class="s">관심 순환 속도</div></div>
 <div class="stat mimosa"><div class="k">차트 신호</div><div class="v" id="mimosaStatus">-</div><div class="s" id="mimosaSub"></div></div>
</div>

<div class="tabs" id="tabs">
 <button class="tab active" data-view="home">홈</button>
 <button class="tab" data-view="index">지수</button>
 <button class="tab" data-view="query">조회순위</button>
 <button class="tab" data-view="sector">섹터</button>
 <button class="tab" data-view="trade">거래대금</button>
 <button class="tab" data-view="material">재료·뉴스</button>
 <button class="tab" data-view="research">리서치</button>
 <button class="tab" data-view="brokerage">AI 증권사</button>
 <button class="tab" data-view="mimosa">미모사</button>
</div>

<section class="view active" id="view-home">
 <div class="section-title"><h2>오늘 장</h2><span>핵심 흐름만 먼저 · 상세 해석은 접어서 확인</span></div>
 <div id="homeBrief" class="home-brief"><b>시장 핵심</b><span>관측 데이터 축적 중</span></div>
 <div class="home-market-tools">
   <div class="legend" id="quickSignals"></div>
   <details class="market-detail"><summary>상세 시장 해석</summary><div id="analysis"></div></details>
 </div>
 <div class="section-title"><h2>오늘 주도 흐름</h2><span>주도섹터 · 거래대금 강세주 · 최근 4주 반복 테마</span></div>
 <div class="leader-desk">
  <div class="leader-panel"><div class="leader-panel-head"><b>실시간 주도섹터</b><span>+4% 강세주 묶음</span></div><div class="leader-panel-body" id="homeLeaderSectors"></div></div>
  <div class="leader-panel"><div class="leader-panel-head"><b>거래대금 상위 · +4% 이상 상승</b><span>현재가 · 등락 · 거래대금</span></div><div id="homeStrongTurnover"></div></div>
  <div class="leader-panel"><div class="leader-panel-head"><b>최근 4주 주도섹터</b><span id="homeCalendarMeta">저장 이력 기준</span></div><div class="leader-panel-body"><div class="calendar-wrap"><div id="homeLeaderCalendar"></div></div></div></div>
 </div>
 <div class="section-title"><h2>상세 테마·섹터</h2><span>테마 강도 · 종목별 거래대금 · 상승 이유</span></div>
 <div class="sector-grid" id="homeSectors"></div>
 <div class="section-title"><h2>급부상 종목</h2><span>순위변화 · 거래대금 · 재료색 · OS 교차확인</span></div>
 <div id="homeMaterialLegend" class="material-legend"></div>
 <div id="homeSectorMix" class="surge-sector-bar"></div>
 <div class="panel"><div class="tblwrap"><table class="tbl"><thead><tr><th>조회·변화</th><th class="left">종목</th><th>등락</th><th>대금순위</th><th>거래대금</th><th class="left">섹터</th><th class="left">흐름</th><th class="left">재료·OS</th><th class="left">차트·고점/바닥</th></tr></thead><tbody id="homeStocks"></tbody></table></div></div>
 <div class="section-title"><h2>관찰 후보 Top5</h2><span>후보 추적기가 현재 유지 중인 종목 · 추천/주문 아님</span></div>
 <div id="homeCandidates" class="home-candidates"></div>
 <div class="section-title"><h2>Paper Lab · 자동 가상매매</h2><span>레이더 규칙 검증용 · 1단위 · 실계좌 주문 없음</span></div>
 <div id="homePaperLab" class="paper-lab"></div>
 <div id="homePaperFeedback" class="paper-feedback"></div>
</section>

<section class="view" id="view-brokerage">
 <div class="broker-hero">
  <div>
   <div class="broker-eyebrow">AI BROKERAGE OS · PAPER-FIRST</div>
   <h2>감으로 고르는 종목이 아니라<br>근거가 통과한 전략만 다음 단계로</h2>
   <p>시장·재료·수급·차트·전략·리스크를 한 점수로 뭉개지 않습니다. 여섯 Desk가 각자 다른 질문을 던지고, 전략 조건과 Risk Gate를 모두 통과한 경우에만 PAPER 실행 후보가 됩니다.</p>
  </div>
  <div class="broker-mode"><strong id="brokerMode">PAPER ONLY</strong><span id="brokerStatus">실계좌 주문 경로 없음</span></div>
 </div>
 <div class="section-title"><h2>하루의 운영 루프</h2><span>관찰 → 교차검증 → 전략선택 → 거부권 → 가상실행 → 복기</span></div>
 <div class="broker-cycle">
  <div class="broker-step"><i>01 OBSERVE</i><b>시장 읽기</b><span>장세·섹터·관심·거래대금</span></div>
  <div class="broker-step"><i>02 CROSS-CHECK</i><b>근거 검증</b><span>뉴스·DART·Telegram 신원 확인</span></div>
  <div class="broker-step"><i>03 MATCH</i><b>전략 매칭</b><span>50-slot Registry의 현재 조건 비교</span></div>
  <div class="broker-step"><i>04 VETO</i><b>Risk 거부권</b><span>데이터 지연·손실·중복포지션 차단</span></div>
  <div class="broker-step"><i>05 PAPER</i><b>가상 실행</b><span>실제 주문 전 forward-test 축적</span></div>
  <div class="broker-step"><i>06 REVIEW</i><b>성과 귀속</b><span>어떤 전략·장세·판단이 맞았는지 기록</span></div>
 </div>
 <div class="section-title"><h2>Morning Brief</h2><span>오늘 무엇을 살지보다 먼저 · 어떤 장에서 어떤 전략을 쓸지</span></div>
 <div id="brokerMorning" class="broker-brief"></div>
 <div class="section-title"><h2>6개 Desk</h2><span>한 AI의 자신감보다 서로 다른 책임의 분리</span></div>
 <div class="broker-desks">
  <div class="broker-desk"><b>Market Desk · 시장부</b><p>현재 장세의 추세·수급 분포·심리와 데이터 신선도를 판단합니다.</p></div>
  <div class="broker-desk"><b>Catalyst Desk · 재료부</b><p>뉴스·공시·Telegram의 재료 강도뿐 아니라 실제 종목과의 identity가 맞는지 확인합니다.</p></div>
  <div class="broker-desk"><b>Flow Desk · 수급부</b><p>조회순위, 순위 가속, 최근 거래대금과 섹터 확산을 분리해 봅니다.</p></div>
  <div class="broker-desk"><b>Technical Desk · 기술부</b><p>MIMOSA 상태, 추세 유지·M수렴·돌파·전고점·고점 경계를 판독합니다.</p></div>
  <div class="broker-desk"><b>Strategy Desk · 전략부</b><p>전략 이름을 추천하는 대신 현재 regime·chart·material gate를 실제 Registry와 대조합니다.</p></div>
  <div class="broker-desk"><b>Risk Desk · 리스크부</b><p>포지션 수, 일일 손실, 시세 freshness, 중복 보유를 보고 최종 거부권을 가집니다.</p></div>
 </div>
 <div class="section-title"><h2>Strategy Factory</h2><span>50개 슬롯을 보유하되 검증되지 않은 전략은 ACTIVE처럼 표시하지 않음</span></div>
 <div id="brokerRegistry" class="broker-registry"></div>
 <div class="section-title"><h2>Strategy Performance</h2><span>전략 이름이 아니라 실제 Paper 표본으로 비교</span></div>
 <div id="brokerPerformance" class="strategy-perf"></div>
 <div class="section-title"><h2>Capacity & Final Lifecycle Gate</h2><span>Paper edge가 실제 체결과 규모를 버티는지 검증</span></div>
 <div id="brokerCapacity" class="strategy-perf"></div>
 <div class="section-title"><h2>Capital Allocation Optimizer</h2><span>edge × capacity × correlation × portfolio risk</span></div>
 <div id="brokerAllocation" class="allocation-lab"></div>
 <div class="section-title"><h2>Shadow Execution Simulator</h2><span>신호와 체결을 분리 · 슬리피지·부분체결·포지션 크기 추정</span></div>
 <div id="brokerShadow" class="shadow-lab"></div>
 <div class="section-title"><h2>오늘의 6-Desk 회의 결과</h2><span>WATCH · READY · PAPER_ENTRY · BLOCKED를 이유와 함께 공개</span></div>
 <div id="brokerCandidates" class="broker-candidates"></div>
 <div class="section-title"><h2>19:00 Daily Review</h2><span>수익보다 먼저 · 오늘의 판단·차단·실패 패턴 복기</span></div>
 <div id="brokerDailyReview" class="daily-review"></div>
 <div class="section-title"><h2>우리의 기준</h2><span>자동화보다 중요한 것은 무엇을 자동화하느냐</span></div>
 <div class="broker-principle">
  <div><b>예측보다 검증</b><span>AI가 시장을 맞힌다고 가정하지 않고, 확인 가능한 근거와 조건을 남깁니다.</span></div>
  <div><b>점수보다 거부권</b><span>높은 종합점수도 데이터 지연·차트 훼손·손실한도에 걸리면 실행하지 않습니다.</span></div>
  <div><b>자가수정보다 성과 귀속</b><span>AI가 몰래 규칙을 바꾸지 않고, 먼저 전략별 결과를 축적해 승격·강등 근거로 사용합니다.</span></div>
 </div>
</section>

<section class="view" id="view-index">
 <div class="section-title"><h2>KOSPI · KOSDAQ 지수차트</h2><span>Kiwoom ka20005 분봉 / ka20006 일봉</span></div>
 <div class="index-grid">
  <div class="chart-card"><div class="chart-title"><div><b>KOSPI · 5분</b><div class="sub">장중 흐름</div></div><div id="kospiIntraLast"></div></div><div id="kospiIntra"></div></div>
  <div class="chart-card"><div class="chart-title"><div><b>KOSDAQ · 5분</b><div class="sub">장중 흐름</div></div><div id="kosdaqIntraLast"></div></div><div id="kosdaqIntra"></div></div>
  <div class="chart-card"><div class="chart-title"><div><b>KOSPI · 일봉</b><div class="sub">최근 120거래일</div></div><div id="kospiDailyLast"></div></div><div id="kospiDaily"></div></div>
  <div class="chart-card"><div class="chart-title"><div><b>KOSDAQ · 일봉</b><div class="sub">최근 120거래일</div></div><div id="kosdaqDailyLast"></div></div><div id="kosdaqDaily"></div></div>
 </div>
 <div class="panel pad" style="margin-top:8px"><b>지수 해석</b><div class="sub" style="margin-top:5px">지수 방향과 조회집중·거래대금 집중을 함께 봅니다. 지수 상승만으로 주도주 장세로 판단하지 않고, 대형주 집중인지 수급 확산인지 분리합니다.</div></div>
</section>

<section class="view" id="view-query">
 <div class="section-title"><h2>실시간 종목조회 순위</h2><span>사람들이 지금 무엇을 보고 있는가</span></div>
 <div class="panel"><div class="tblwrap"><table class="tbl"><thead><tr><th>순위</th><th>변화</th><th class="left">종목</th><th>등락</th><th>거래대금</th><th>시총대비*</th><th class="left">섹터</th><th class="left">흐름</th><th class="left">재료</th><th class="left">미모사</th></tr></thead><tbody id="queryRows"></tbody></table></div></div>
</section>

<section class="view" id="view-sector">
 <div class="section-title"><h2>섹터별 실시간 순위</h2><span>왜 오르는지 · 어디서 거래대금이 터지는지</span></div>
 <div class="sector-grid" id="sectorBoard"></div>
 <div class="section-title"><h2>공식 업종 데이터</h2><span>키움 업종 등락·거래대금</span></div>
 <div class="panel"><div class="tblwrap"><table class="tbl"><thead><tr><th class="left">업종</th><th>등락</th><th>거래대금</th><th>상승</th><th>하락</th></tr></thead><tbody id="officialSectors"></tbody></table></div></div>
</section>

<section class="view" id="view-trade">
 <div class="section-title"><h2>거래대금 순위 · 주식</h2><span>ETF/ETN 제외, 실제 종목 수급 중심</span></div>
 <div class="panel"><div class="tblwrap"><table class="tbl"><thead><tr><th>대금순위</th><th class="left">종목</th><th>등락</th><th>거래대금</th><th>조회순위</th><th>시총대비*</th><th class="left">섹터</th><th class="left">흐름</th><th class="left">재료 요약</th><th class="left">미모사</th></tr></thead><tbody id="tradeRows"></tbody></table></div></div>
 <div class="section-title"><h2>ETF / ETN 거래대금</h2><span>시장 방향성 참고용으로 분리</span></div>
 <div class="panel"><div class="tblwrap"><table class="tbl"><thead><tr><th>대금순위</th><th class="left">ETF/ETN</th><th>등락</th><th>거래대금</th><th class="left">비고</th></tr></thead><tbody id="etfTradeRows"></tbody></table></div></div>
</section>

<section class="view" id="view-material">
 <div class="section-title"><h2>재료·뉴스 종합</h2><span>원문 나열보다 요약·판정 먼저</span></div>
 <div class="material-grid" id="materials"></div>
</section>

<section class="view" id="view-research">
 <div class="section-title"><h2>멀티에이전트 종합 리포트</h2><span>수급 · 공시 · 뉴스 · Telegram · 섹터 · 미모사 교차검증</span></div>
 <div class="panel pad" style="margin-bottom:8px"><b id="deepResearchStatus">Deep Research Engine 대기</b><div class="sub" style="margin-top:5px">현재는 Mac mini 내부 데이터를 8개 분석축으로 분리해 교차검증하는 로컬 멀티에이전트 v1입니다.</div></div>
 <div class="deep-grid" id="deepResearchCards"></div>

 <div class="section-title"><h2>Research Agent 큐</h2><span>조회 급등 · 거래대금 신규진입 · 돈 선행 재료미확인 자동 감지</span></div>
 <div class="panel pad" style="margin-bottom:8px"><b id="researchStatus">Research Engine 대기</b><div class="sub" style="margin-top:5px">우선순위가 높은 종목만 멀티에이전트 분석으로 넘깁니다.</div></div>
 <div class="research-grid" id="researchCards"></div>
</section>

<section class="view" id="view-mimosa">
 <div class="section-title"><h2>미모사 · 기본 차트 상태</h2><span>M수렴 · 전고 · 추세 · 돌파</span></div>
 <div class="panel pad" style="margin-bottom:8px"><b>기본 기준</b><div class="legend" style="margin-top:7px"><span class="pill">M 수렴</span><span class="pill">M 수렴 후 돌파</span><span class="pill">전고점 접근</span><span class="pill">돌파 후 지지</span><span class="pill">분봉 추세 유지</span><span class="pill">추세 훼손</span></div></div>
 <div class="mimosa-grid" id="mimosaCards"></div>

 <div class="section-title"><h2>종가베팅 레이더</h2><span>NXT 당일 주도주 · 거래대금+신고가 · KRX 연속상승</span></div>
 <div class="panel pad" style="margin-bottom:8px"><div class="sub">5강 강사 피드백을 중심으로 분봉 추세 유지, 거래대금, 신고가/연속상승을 분리해 표시합니다. 시스템의 수치 임계값은 검증용 운영값입니다.</div></div>
 <div class="strategy-grid" id="closeBetCards"></div>

 <div class="section-title"><h2>과대낙폭 레이더</h2><span>최근 주도주 · 중기 고점 대비 하락 · 관심 유지</span></div>
 <div class="panel pad" style="margin-bottom:8px"><div class="sub">최근 주도주가 고점 대비 크게 밀린 뒤에도 조회·거래대금 관심이 남아 있는지를 감시합니다. 25~45% 낙폭 등 수치는 운영 v1이며 즉시 진입 신호가 아닙니다.</div></div>
 <div class="strategy-grid" id="oversoldCards"></div>

 <div class="section-title"><h2>낙주 레이더</h2><span>당일 강세주가 장중 급락하는 구조</span></div>
 <div class="panel pad" style="margin-bottom:8px"><div class="sub">과대낙폭과 분리합니다. 당일 거래대금·조회 관심이 유지된 강세주가 고점 대비 급락했는지, 최근 분봉에서 매도 속도가 둔화되는지를 감시합니다.</div></div>
 <div class="strategy-grid" id="fallingCards"></div>
</section>
</div>

<div class="bottom" id="bottom">
 <button class="active" data-view="home"><b>⌂</b>홈</button><button data-view="index"><b>⌁</b>지수</button><button data-view="query"><b>⌕</b>조회</button><button data-view="sector"><b>▦</b>섹터</button><button data-view="trade"><b>₩</b>대금</button><button data-view="material"><b>◆</b>재료</button><button data-view="research"><b>R</b>리서치</button><button data-view="brokerage"><b>AI</b>증권사</button><button data-view="mimosa"><b>M</b>미모사</button>
</div>

<script>
let token=location.hash.slice(1)||localStorage.getItem("marketRadarToken")||"";
if(location.hash){localStorage.setItem("marketRadarToken",token);history.replaceState(null,"",location.pathname);}
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));
const fmt=(v,d=1)=>v==null?"-":Number(v).toLocaleString("ko-KR",{maximumFractionDigits:d});
const rate=v=>v==null?"-":fmt(v)+"%";
const klass=v=>Number(v)>0?"hot":Number(v)<0?"bad":"";
const money=v=>v==null?"-":fmt(Number(v)/1e8)+"억";
const obsPct=v=>v==null||!Number.isFinite(Number(v))?"—":(Number(v)>0?"+":"")+fmt(Number(v),2)+"%";
const retClass=v=>Number(v)>0?"hot":Number(v)<0?"bad":"";
const pct=v=>v==null?"-":(Number(v)*100).toFixed(1)+"%";
let DATA=null;
function sectorName(x){return x?.market_theme||x?.official_sector||x?.sector||"미분류"}
function sectorClass(name){
 let h=0;for(const c of String(name||"미분류"))h=((h*31)+c.charCodeAt(0))>>>0;
 return "sc"+(h%8);
}
function sectorChip(name,extra=""){
 const n=name||"미분류",c=sectorClass(n);
 return '<span class="sector-chip '+c+'"><i></i>'+esc(n)+(extra?' · '+esc(extra):'')+'</span>';
}
function recentMoney(x){
 if(x?.recent_turnover_krw==null)return "";
 const sec=x.recent_turnover_seconds==null?"최근":Math.round(Number(x.recent_turnover_seconds))+"초";
 return sec+" +"+money(x.recent_turnover_krw);
}
function signalBadge(x){
 const s=x?.reversal_signal;if(!s)return "";
 const cls=s.kind==="TOP_WARNING"?"signal-top":"signal-bottom";
 const icon=s.kind==="TOP_WARNING"?"▼":"▲";
 return '<span class="signal-badge '+cls+'" title="'+esc((s.reasons||[]).join(" · "))+'">'+icon+' '+esc(s.label||"관찰")+' '+esc(s.score??"-")+'</span>';
}
function materialTone(type){
 const map={"수주·공급계약":"mt-contract","실적·가이던스":"mt-earnings","기술·제품·양산":"mt-product","정책·규제":"mt-policy","승인·임상":"mt-clinical","자본·주주환원":"mt-capital","업황·가격":"mt-industry","인수·사업재편":"mt-ma","기타·미확인":"mt-unknown"};
 return map[type]||"mt-unknown";
}
function materialTag(d){
 const type=d?.material_type||"기타·미확인";
 return '<span class="material-tag '+materialTone(type)+'">'+esc(type)+'</span>';
}
function rankMovement(x){
 const h=x?.rank_history||{},kind=h.movement_kind||"FLAT",cls=kind==="UP"?"rank-up":kind==="DOWN"?"rank-down":kind==="NEW"?"rank-new":kind==="REENTRY"?"rank-re":"rank-flat";
 return '<span class="rank-move '+cls+'">'+esc(h.movement||"—")+'</span>'+
   '<div class="rank-history">30초 '+esc(h.rank_30s??"-")+' · 5분 '+esc(h.rank_5m??"-")+' · 오늘최고 '+esc(h.best_today??"-")+'</div>';
}
function clipText(v,n=110){const t=String(v||"").replace(/\s+/g," ").trim();return t.length>n?t.slice(0,n)+"…":t;}
function sourceMini(x){
 const c=x?.catalyst||{},links=[];
 for(const d of (c.dart||[]).slice(0,1))if(d.link)links.push('<a href="'+esc(d.link)+'" target="_blank" rel="noopener">DART</a>');
 for(const n of (c.external_news||[]).slice(0,2))if(n.link)links.push('<a href="'+esc(n.link)+'" target="_blank" rel="noopener">'+esc(n.source||"기사")+'</a>');
 return links.length?'<div class="os-links">'+links.join("")+'</div>':"";
}
function osMini(x){
 const r=x?.external_research;if(!r)return "";
 const links=(r.sources||[]).slice(0,2).map((s,i)=>'<a href="'+esc(s.url||"#")+'" target="_blank" rel="noopener">출처'+(i+1)+'</a>').join("");
 return '<div class="os-mini"><b>'+(r.stale?'과거 OS':'OS 외부조사')+' · '+esc(r.citation_count??0)+'인용</b><div>'+esc(clipText(r.summary||"인용 포함 조사",115))+'</div>'+(links?'<div class="os-links">'+links+'</div>':'')+'</div>';
}
function renderLeaderSectors(desk){
 const xs=desk?.leading_sectors||[];
 if(!xs.length)return '<div class="muted" style="padding:10px">+4% 강세주 기준 주도섹터 대기</div>';
 return xs.slice(0,3).map(g=>{
   const cls=sectorClass(g.name),why=g.reason||{},stocks=(g.stocks||[]).slice(0,4).map(x=>
     '<div class="lead-stock"><b>'+esc(x.name||x.code)+'</b><span style="text-align:right;font-weight:800">'+esc(x.current_price_krw==null?"-":fmt(x.current_price_krw,0))+'</span><span class="ls-change '+klass(x.change_rate)+'">'+esc(rate(x.change_rate))+'</span><span class="ls-money">'+esc(money(x.trade_value_krw))+'</span></div>'
   ).join("");
   return '<div class="lead-sector '+cls+'"><div class="lead-sector-head"><div><b>'+esc(g.name)+'</b><div class="ls-meta">'+esc(g.count)+'종목 · 평균 '+esc(rate(g.avg_change_rate))+'</div><div class="lead-sector-strength">테마 강도 '+esc(g.theme_strength??"-")+(g.theme_strength_label?' · '+esc(g.theme_strength_label):'')+'</div></div><div><b>'+esc(money(g.trade_value_krw))+'</b></div></div><div class="lead-sector-stocks">'+stocks+'</div><div class="lead-sector-reason"><b>왜 강한가</b> · '+esc(clipText(why.summary||"공통 재료 분석 대기",115))+'</div></div>';
 }).join("");
}
function renderStrongTurnover(desk){
 const xs=desk?.strong_stocks||[];
 if(!xs.length)return '<div class="muted" style="padding:12px">거래대금 상위 +4% 종목 없음</div>';
 const head='<div class="strong-head"><span>대금</span><span>종목/테마</span><span style="text-align:right">현재가</span><span style="text-align:right">등락</span><span style="text-align:right">거래대금</span></div>';
 const rows=xs.slice(0,12).map(x=>'<div class="strong-row '+sectorClass(x.theme)+'"><span class="sr-rank">#'+esc(x.trade_rank??"-")+'</span><span class="sr-name">'+esc(x.name||x.code)+'<span class="strong-theme">· '+esc(x.theme||"미분류")+'</span></span><span class="sr-price">'+esc(x.current_price_krw==null?"-":fmt(x.current_price_krw,0))+'</span><span class="sr-change '+klass(x.change_rate)+'">'+esc(rate(x.change_rate))+'</span><span class="sr-money">'+esc(money(x.trade_value_krw))+'</span></div>').join("");
 return head+rows;
}
function renderLeaderCalendar(cal){
 const weekdays=['월','화','수','목','금'],cells=cal?.cells||[];
 let html='<div class="leader-calendar">'+weekdays.map(x=>'<div class="cal-head">'+x+'</div>').join("");
 html+=cells.map(c=>{
   const themes=(c.themes||[]).map(t=>'<span class="cal-theme '+sectorClass(t.theme)+'" title="'+esc(t.count+'종목 · '+money(t.trade_value_krw))+'">• '+esc(t.theme)+'</span>').join("");
   return '<div class="cal-cell '+(c.future?'future':'')+'"><div class="cal-date">'+esc(c.day)+'</div>'+(themes||'<span class="muted" style="font-size:9px">'+(c.future?'예정':'이력 없음')+'</span>')+'</div>';
 }).join("");
 html+='</div><div class="calendar-note">저장 이력이 있는 날짜만 표시 · 각 날짜 마지막 거래대금 스냅샷의 +4% 이상 종목 기준</div>';
 return html;
}
function renderMaterialLegend(){
 const xs=[
  ["수주·공급계약","mt-contract"],["실적·가이던스","mt-earnings"],["기술·제품·양산","mt-product"],
  ["정책·규제","mt-policy"],["승인·임상","mt-clinical"],["업황·가격","mt-industry"],["기타·미확인","mt-unknown"]
 ];
 return '<span class="legend-label">재료색</span>'+xs.map(x=>'<span class="material-tag '+x[1]+'">'+x[0]+'</span>').join("");
}
function renderSectorMix(rows){
 const top=(rows||[]).slice(0,12),groups={};
 top.forEach(x=>{const n=sectorName(x),g=groups[n]||(groups[n]={name:n,count:0,money:0,recent:0});g.count++;g.money+=Number(x.trade_value_krw||0);g.recent+=Number(x.recent_turnover_krw||0)});
 const xs=Object.values(groups).sort((a,b)=>(b.count-a.count)||(b.recent-a.recent)||(b.money-a.money));
 return xs.map(g=>{const src=(DATA?.sector_rankings||[]).find(x=>x.name===g.name)||{};return sectorChip(g.name,"강도 "+(src.theme_strength??"-")+" · "+g.count+"개 · "+money(g.money)+(g.recent>0?" / 최근 +"+money(g.recent):""));}).join("")||'<span class="muted">급부상 섹터 집계 대기</span>';
}
function strengthBlock(g,detail=false){
 const score=Number(g?.theme_strength||0),label=g?.theme_strength_label||"대기",c=g?.theme_strength_components||{};
 const title='관심 '+fmt(c.interest,1)+' · 돈 '+fmt(c.money,1)+' · 확산 '+fmt(c.breadth,1)+' · 가격 '+fmt(c.price,1)+' · 급부상 '+fmt(c.surge,1)+' · 재료 '+fmt(c.material,1);
 return '<div class="theme-strength" title="'+esc(title)+'"><div class="theme-strength-top"><span>테마 강도</span><b>'+esc(score)+'/100 · '+esc(label)+'</b></div>'+
   '<div class="theme-strength-bar"><i style="width:'+Math.max(0,Math.min(100,score))+'%"></i></div>'+
   (detail?'<div class="theme-components">'+esc(title)+'</div>':'')+'</div>';
}
function renderSectorPulse(sectors,rows){
 const top=(rows||[]).slice(0,12),counts={};
 top.forEach(x=>{const n=sectorName(x);counts[n]=(counts[n]||0)+1});
 return (sectors||[]).slice(0,4).map(g=>{
   const n=g.name||"미분류",c=sectorClass(n),why=g.reason||{};
   const cnt=counts[n]||0,recent=g.recent_turnover_known?money(g.recent_turnover_krw):"비교대기";
   return '<div class="sector-pulse-card '+c+'"><div class="sp-name">'+esc(n)+'</div>'+
     '<div class="sp-count">'+cnt+'개 <span class="'+klass(g.avg_change_rate)+'" style="font-size:12px">'+esc(rate(g.avg_change_rate))+'</span></div>'+
     '<div class="sp-money">누적 '+esc(money(g.trade_value_krw))+' · 최근 '+esc(recent)+'</div>'+
     strengthBlock(g,false)+
     '<div class="sp-reason">'+esc(why.label||"공통재료 미확인")+' · '+esc(why.summary||"")+'</div></div>';
 }).join("")||'<div class="panel pad muted">섹터 흐름 집계 대기</div>';
}

function setView(name){
 document.querySelectorAll(".view").forEach(x=>x.classList.toggle("active",x.id==="view-"+name));
 document.querySelectorAll("[data-view]").forEach(x=>x.classList.toggle("active",x.dataset.view===name));
}
document.querySelectorAll("[data-view]").forEach(b=>b.onclick=()=>setView(b.dataset.view));

async function sendFeedback(category,stock,predicted,verdict,btn){
 try{
  const r=await fetch("/api/feedback",{method:"POST",headers:{"content-type":"application/json","x-dashboard-token":token},
    body:JSON.stringify({category:category,stock_code:stock,predicted_state:predicted,verdict:verdict})});
  if(!r.ok)throw new Error("HTTP "+r.status);
  if(btn){btn.classList.add("sent");btn.textContent="저장됨";}
 }catch(e){if(btn)btn.textContent="실패";console.error(e);}
}


function digest(x){return x?.material_digest||x?.digest||{}}
function sectorCards(list,limit=8,showStrength=false){
 return (list||[]).slice(0,limit).map(g=>{
   const xs=(g.stocks||[]).slice(0,6),maxMoney=Math.max(1,...xs.map(x=>Number(x.trade_value_krw||0)));
   const stocks=xs.map(x=>{
     const width=Math.max(2,Math.min(100,Number(x.trade_value_krw||0)/maxMoney*100));
     const d=x.material_digest||{},mv=(DATA?.query_ranking||[]).find(r=>r.code===x.code);
     return '<div class="stock-mini"><div class="name">'+esc(x.name||x.code)+'</div>'+
       '<div class="num"><div><span class="rank-badge">#'+esc(x.rank??"-")+'</span> '+(mv?rankMovement(mv):'')+'</div><span class="'+klass(x.change_rate)+'">'+esc(rate(x.change_rate))+'</span></div>'+
       '<div class="stock-money">'+esc(money(x.trade_value_krw))+' <span class="sub">대금 #'+esc(x.trade_rank??"-")+'</span></div>'+
       '<div class="stock-burst">'+esc(recentMoney(x)||"최근구간 비교대기")+'</div>'+
       '<div class="material-meta">'+materialTag(d)+'</div>'+
       '<div class="moneybar"><i style="width:'+width.toFixed(1)+'%"></i></div></div>';
   }).join("");
   const why=g.reason||{},reasonClass=why.level==="SUPPORTED"?"supported":why.level==="PARTIAL"?"partial":"unconfirmed";
   const evLimit=showStrength?2:3;
   const evidence=(why.evidence||[]).slice(0,evLimit).map(x=>'<span class="pill">'+esc(x.name||x.code)+' · '+esc(x.assessment||"재료")+'</span>').join("");
   const evidenceLines=(why.evidence||[]).slice(0,evLimit).map(x=>'<div class="sector-evidence-line"><b>'+esc(x.name||x.code)+'</b> · '+esc(clipText(x.summary||x.assessment||"재료 확인",showStrength?90:140))+'</div>').join("");
   const recent=g.recent_turnover_known?(' · 최근 '+money(g.recent_turnover_krw)):'';
   const hotCount=((DATA?.query_ranking)||[]).slice(0,12).filter(x=>sectorName(x)===g.name).length;
   return '<div class="sector-card '+sectorClass(g.name)+'"><div class="sector-head"><div><strong>'+esc(g.name)+'</strong> '+(hotCount?'<span class="sector-chip '+sectorClass(g.name)+'"><i></i>급부상 '+hotCount+'개</span>':'')+
     '<div class="sector-meta">조회상위 '+esc(g.count)+'종목 · 상승 '+esc(g.positive??0)+'/'+esc(g.change_n??g.count)+'</div>'+
     '<div class="sector-money">누적 '+esc(money(g.trade_value_krw))+esc(recent)+'</div>'+(showStrength?strengthBlock(g,false):'')+'</div>'+
     '<div class="'+klass(g.avg_change_rate)+'"><b>'+esc(rate(g.avg_change_rate))+'</b></div></div>'+
     '<div class="stock-list">'+stocks+'</div>'+
     '<div class="sector-reason '+reasonClass+'"><b>왜 움직이나 · '+esc(why.label||"분석 대기")+'</b><div title="'+esc(why.summary||"")+'">'+esc(clipText(why.summary||"섹터 재료 분석 대기",showStrength?125:220))+'</div>'+
     (evidence?'<div class="sector-evidence">'+evidence+'</div>':'')+
     (evidenceLines?'<div class="sector-evidence-lines">'+evidenceLines+'</div>':'')+'</div></div>';
 }).join("")||'<div class="panel pad muted">섹터 데이터 대기 중</div>';
}
function stockRow(x,mode){
 const d=digest(x), q=x.rank??x.query_rank, t=x.trade_rank;
 const c=x.mimosa||{};
 const first=mode==="trade"?'<td>'+esc(t??"-")+'</td>':'<td><b>'+esc(q??"-")+'</b>'+rankMovement(x)+'</td>';
 const change=(mode==="query")?'<td class="'+(Number(x.rank_change)>0?"hot":Number(x.rank_change)<0?"bad":"")+'">'+esc(x.rank_change==null?"-":(x.rank_change>0?"↑":"↓")+Math.abs(x.rank_change))+'</td>':"";
 return '<tr>'+first+change+
 '<td class="left"><span class="stockname">'+esc(x.name||x.code)+'</span><div class="sub">'+esc(x.code)+'</div></td>'+
 '<td class="'+klass(x.change_rate)+'">'+esc(rate(x.change_rate))+'</td>'+
 (mode==="query"?'<td>'+esc(money(x.trade_value_krw))+'</td>':'<td>'+esc(money(x.trade_value_krw))+'</td><td>'+esc(q??"-")+'</td>')+
 '<td>'+esc(x.trade_to_cap_pct==null?"-":Number(x.trade_to_cap_pct).toFixed(1)+"%")+'</td>'+
 '<td class="left">'+sectorChip(sectorName(x))+'</td>'+
 '<td class="left"><span class="pill">'+esc(x.flow_state||"관찰")+'</span></td>'+
 '<td class="material-cell"><div class="material-meta">'+materialTag(d)+'</div><div class="material-main" title="'+esc(d.summary||"")+'">'+esc(clipText(d.summary||"재료 미확인",130))+'</div><div class="sub">'+esc(d.assessment||"")+'</div>'+sourceMini(x)+osMini(x)+'</td>'+
 '<td class="left"><b>'+esc(c.state_ko||x.chart_state||"대기")+'</b><div class="sub">'+esc(c.minute_trend||"")+'</div>'+signalBadge(x)+'</td></tr>';
}
function renderHomeStocks(rows){
 return (rows||[]).slice(0,12).map(x=>{
   const d=digest(x),m=x.mimosa||{},sector=sectorName(x),recent=recentMoney(x);
   return '<tr class="surge-row '+sectorClass(sector)+'">'+
   '<td><b>#'+esc(x.rank??"-")+'</b>'+rankMovement(x)+'</td>'+
   '<td class="left"><b>'+esc(x.name||x.code)+'</b><div class="sub">'+esc(x.code||"")+'</div></td>'+
   '<td class="'+klass(x.change_rate)+'">'+esc(rate(x.change_rate))+'</td><td>'+esc(x.trade_rank??"-")+'</td>'+
   '<td><b>'+esc(money(x.trade_value_krw))+'</b>'+(recent?'<div class="sub">'+esc(recent)+'</div>':'')+'</td>'+
   '<td class="left">'+sectorChip(sector)+'</td><td class="left"><span class="pill">'+esc(x.flow_state||"관찰")+'</span></td>'+
   '<td class="material-cell"><div class="material-meta">'+materialTag(d)+'<span class="pill">'+esc(d.newness||"")+'</span></div>'+
   '<div class="material-main" title="'+esc(d.summary||"")+'">'+esc(clipText(d.summary||"직접 재료 미확인",105))+'</div><div class="sub">'+esc(d.assessment||"")+' · 뉴스 '+esc(d.news_count??0)+' · 공시 '+esc(d.dart_count??0)+'</div>'+sourceMini(x)+osMini(x)+'</td>'+
   '<td class="left"><b>'+esc(m.state_ko||x.chart_state||"대기")+'</b>'+signalBadge(x)+'</td></tr>';
 }).join("")||'<tr><td colspan="9" class="muted">장중 실시간 데이터 대기 중</td></tr>';
}
function renderHomeCandidates(rows){
 const xs=rows||[];
 if(!xs.length)return '<div class="panel pad muted" style="grid-column:1/-1">현재 유지 중인 관찰 후보가 없습니다.</div>';
 return xs.slice(0,5).map(x=>{
   const sig=x.reversal_signal||{},sigText=sig.kind==="TOP_WARNING"?'▼ 고점 '+sig.score:sig.kind==="BOTTOM_WATCH"?'▲ 바닥 '+sig.score:'';
   const move=(x.rank_history||{}).movement||"—";
   return '<article class="home-candidate"><div class="hc-top"><div><div class="hc-name">'+esc(x.name||x.code)+'</div><div class="hc-meta">'+esc(x.market_theme||"테마 미확인")+' · '+esc(x.primary_type||"관찰")+'</div></div><div class="hc-score">'+esc(x.attention_score??"-")+'</div></div>'+
     '<div class="hc-money">최근 '+esc(money(x.recent_turnover_krw))+' · 누적 '+esc(money(x.trade_value_krw))+'</div>'+
     '<div class="hc-meta">등락 '+esc(rate(x.change_rate))+' · 조회 '+esc(x.rank??"-")+' '+esc(move)+' · 대금 #'+esc(x.trade_rank??"-")+'</div>'+
     '<div class="hc-tags"><span class="pill">'+esc(x.event_type||"재료 미확인")+'</span>'+(x.chart_state?'<span class="pill">'+esc(x.chart_state)+'</span>':'')+(sigText?'<span class="signal-badge '+(sig.kind==="TOP_WARNING"?"signal-top":"signal-bottom")+'">'+esc(sigText)+'</span>':'')+'</div></article>';
 }).join("");
}
function renderAIMorningBrief(x){
 const el=document.getElementById("brokerMorning");if(!el)return;
 const b=x||{},sectors=b.top_sectors||[],strategies=b.active_strategy_candidates||[];
 el.innerHTML=
   '<div class="brief-card main"><div class="brief-k">MARKET REGIME</div><div class="brief-v">'+esc(b.regime||"대기")+'</div><div class="sub">'+esc(b.headline||"시장 데이터 축적 중")+'</div>'+
   '<div class="brief-list">'+sectors.map(s=>'<span class="pill">'+esc(s.name||"미분류")+' '+esc(s.strength==null?"":fmt(s.strength,0))+'</span>').join("")+'</div></div>'+
   '<div class="brief-card"><div class="brief-k">PAPER ENTRY</div><div class="brief-v">'+esc(b.paper_entry_count??0)+'</div><div class="sub">forward-test 후보</div></div>'+
   '<div class="brief-card"><div class="brief-k">READY</div><div class="brief-v">'+esc(b.ready_count??0)+'</div><div class="sub">실행 문턱 전</div></div>'+
   '<div class="brief-card"><div class="brief-k">RISK BLOCKED</div><div class="brief-v">'+esc(b.blocked_count??0)+'</div><div class="sub">거부권 발동</div></div>'+
   (strategies.length?'<div class="brief-card" style="grid-column:1/-1"><div class="brief-k">TODAY STRATEGY CANDIDATES</div><div class="brief-list">'+strategies.map(s=>'<span class="pill">'+esc(s.strategy_id)+" · "+esc(s.name||"")+' · fit '+esc(fmt(s.fit,0))+'</span>').join("")+'</div></div>':'');
}
function renderAIStrategyPerformance(x){
 const el=document.getElementById("brokerPerformance");if(!el)return;
 const p=x||{},rows=p.rows||[],matrix=p.context_matrix||[],life=p.lifecycle_review||[];
 if(!rows.length){el.innerHTML='<div class="pad muted">'+esc(p.note||"전략별 Paper 표본 축적 중")+'</div>';return;}
 const main='<div class="tblwrap"><table><thead><tr><th>전략</th><th>표본</th><th>완료</th><th>양(+)</th><th>평균</th><th>중앙</th><th>PF</th><th>MFE</th><th>MAE</th><th>상태</th></tr></thead><tbody>'+
 rows.slice(0,20).map(r=>'<tr><td><b>'+esc(r.strategy_id)+' · '+esc(r.name||"")+'</b><div class="sub">'+esc(r.family||"")+' · '+esc(r.lifecycle||"")+'</div></td><td>'+esc(r.episodes??0)+'</td><td>'+esc(r.closed??0)+'</td><td>'+esc(r.positive_pct==null?"—":fmt(r.positive_pct,0)+"%")+'</td><td class="'+retClass(r.avg_return_pct)+'">'+esc(r.avg_return_pct==null?"—":obsPct(r.avg_return_pct))+'</td><td class="'+retClass(r.median_return_pct)+'">'+esc(r.median_return_pct==null?"—":obsPct(r.median_return_pct))+'</td><td>'+esc(r.profit_factor==null?"—":fmt(r.profit_factor,2))+'</td><td>'+esc(r.median_mfe_pct==null?"—":obsPct(r.median_mfe_pct))+'</td><td>'+esc(r.median_mae_pct==null?"—":obsPct(r.median_mae_pct))+'</td><td><span class="sp-state">'+esc(r.state||"")+'</span></td></tr>').join("")+
 '</tbody></table></div>';
 const lifecycle=life.length?'<div class="context-head">Lifecycle Review · 자동 적용 없음</div><div class="lifecycle-grid">'+life.slice(0,12).map(r=>{
   const cls=r.action==="PROMOTE_CANDIDATE"?"promote":r.action==="DEMOTE_CANDIDATE"?"demote":r.action==="REWORK_CANDIDATE"?"rework":"";
   const conc=r.max_context_concentration==null?"—":fmt(r.max_context_concentration*100,0)+"%";
   return '<div class="lifecycle-card '+cls+'"><div class="lc-top"><div class="lc-name">'+esc(r.strategy_id)+' · '+esc(r.name||"")+'</div><div class="lc-label">'+esc(r.label||r.action)+'</div></div>'+
    '<div class="lc-meta">완료 '+esc(r.closed)+' · 양(+) '+esc(r.positive_pct==null?"—":fmt(r.positive_pct,0)+"%")+' · 중앙 '+esc(r.median_return_pct==null?"—":obsPct(r.median_return_pct))+' · PF '+esc(r.profit_factor==null?"—":fmt(r.profit_factor,2))+'</div>'+
    '<div class="lc-meta">유효 컨텍스트 '+esc(r.eligible_context_cells)+' · 견고 '+esc(r.robust_context_cells)+' · 최대집중 '+esc(conc)+'</div>'+
    (r.failed_gates?.length?'<div class="lc-meta">미통과: '+esc(r.failed_gates.join(", "))+'</div>':'')+'</div>';
 }).join("")+'</div>':'';
 const context=matrix.length?'<div class="context-wrap"><div class="context-head">Context Matrix · Strategy × Regime × Catalyst × Chart</div><div class="tblwrap"><table class="context-table"><thead><tr><th>전략</th><th>Regime</th><th>Catalyst</th><th>Chart</th><th>n</th><th>양(+)</th><th>중앙</th><th>PF</th><th>MFE</th><th>MAE</th></tr></thead><tbody>'+
 matrix.slice(0,30).map(c=>'<tr><td><b>'+esc(c.strategy_id)+'</b></td><td>'+esc(c.regime)+'</td><td>'+esc(c.catalyst)+'</td><td>'+esc(c.chart_state)+'</td><td>'+esc(c.closed??0)+(c.small_sample?'*':'')+'</td><td>'+esc(c.positive_pct==null?"—":fmt(c.positive_pct,0)+"%")+'</td><td class="'+retClass(c.median_return_pct)+'">'+esc(c.median_return_pct==null?"—":obsPct(c.median_return_pct))+'</td><td>'+esc(c.profit_factor==null?"—":fmt(c.profit_factor,2))+'</td><td>'+esc(c.median_mfe_pct==null?"—":obsPct(c.median_mfe_pct))+'</td><td>'+esc(c.median_mae_pct==null?"—":obsPct(c.median_mae_pct))+'</td></tr>').join("")+
 '</tbody></table></div><div class="sub" style="padding:7px 10px">* 컨텍스트 완료표본 5건 미만 · 승격 견고성 계산에서 제외</div></div>':'';
 el.innerHTML=main+lifecycle+context+'<div class="sub" style="padding:8px 10px">'+esc(p.note||"")+(p.unassigned?(" · 전략 미귀속 기존표본 "+p.unassigned+"건"):"")+'</div>';
}
function renderAICapacity(x){
 const el=document.getElementById("brokerCapacity");if(!el)return;
 const p=x||{},finals=p.final_lifecycle||[],caps=p.strategy_capacity||[],matrix=p.capacity_matrix||[],execRows=p.execution_rows||[];
 if(!finals.length&&!caps.length&&!matrix.length){
   el.innerHTML='<div class="pad muted">'+esc(p.note||"Execution-adjusted capacity 표본 축적 중")+'</div>';return;
 }
 const execMap={};execRows.forEach(r=>execMap[r.strategy_id]=r);
 let gate='<div class="capacity-gate"><b>Final Lifecycle Gate</b> · PAPER 성과만으로 ACTIVE 승격하지 않음 · Execution + BOOK_V2 Capacity 필수</div>';
 gate+='<div class="lifecycle-grid">'+(finals.length?finals.slice(0,12).map(r=>{
   const cls=r.action==="PROMOTE_CANDIDATE_EXECUTION_ADJUSTED"?"promote":(r.action==="EXECUTION_BLOCKED"||r.action==="DEMOTE_OR_REWORK")?"demote":"";
   const e=r.execution||{},c=r.capacity||{};
   return '<div class="lifecycle-card '+cls+'"><div class="lc-top"><div class="lc-name">'+esc(r.strategy_id)+' · '+esc(r.name||"")+'</div><div class="lc-label">'+esc(r.label||r.action)+'</div></div>'+
    '<div class="lc-meta">Paper: '+esc(r.paper_action||"—")+' · Shadow n '+esc(e.closed??0)+' · BOOK '+esc(e.book_coverage_pct==null?"—":fmt(e.book_coverage_pct,0)+"%")+'</div>'+
    '<div class="lc-meta">Net 중앙 '+esc(e.median_net_return_pct==null?"—":obsPct(e.median_net_return_pct))+' · PF '+esc(e.profit_factor==null?"—":fmt(e.profit_factor,2))+' · RT IS '+esc(e.median_round_trip_is_bps==null?"—":fmt(e.median_round_trip_is_bps,1)+"bp")+'</div>'+
    '<div class="lc-meta">Capacity '+esc(c.evidence_capacity_krw==null?"—":money(c.evidence_capacity_krw))+(r.failed_gates?.length?(' · 미통과 '+esc(r.failed_gates.join(", "))):'')+'</div></div>';
 }).join(""):'<div class="muted">최종 lifecycle 표본 대기</div>')+'</div>';
 const capHtml='<div class="context-head">Evidence Capacity · 검증된 범위 안에서만</div><div class="capacity-grid">'+(caps.length?caps.slice(0,12).map(c=>{
   const cls=c.state==="EVIDENCE_SUPPORTED"?"supported":c.state==="NO_SUPPORTED_CAPACITY"?"blocked":"";
   return '<div class="capacity-card '+cls+'"><div class="cap-top"><div class="cap-name">'+esc(c.strategy_id)+' · '+esc(c.strategy_name||"")+'</div><span class="sp-state">'+esc(c.label||c.state)+'</span></div>'+
    '<div class="cap-val">'+esc(c.evidence_capacity_krw==null?"—":money(c.evidence_capacity_krw))+'</div>'+
    '<div class="cap-meta">BOOK 완료 '+esc(c.book_closed??0)+' · regime '+esc(c.regime_count??0)+' · 최고 검증 '+esc(c.highest_supported_bucket||"—")+'</div>'+
    '<div class="cap-meta">empirical '+esc(c.empirical_tested_capacity_krw==null?"—":money(c.empirical_tested_capacity_krw))+' · book Q25 '+esc(c.q25_book_capacity_krw==null?"—":money(c.q25_book_capacity_krw))+'</div></div>';
 }).join(""):'<div class="muted">Capacity 표본 축적 중</div>')+'</div>';
 const matrixHtml=matrix.length?'<div class="context-wrap"><div class="context-head">Capacity Matrix · Strategy × Regime × Liquidity × Spread × Order Size</div><div class="tblwrap"><table class="context-table"><thead><tr><th>전략</th><th>Regime</th><th>Liquidity</th><th>Spread</th><th>Order Size</th><th>n</th><th>Net 중앙</th><th>양(+)</th><th>PF</th><th>Drag</th><th>RT IS</th></tr></thead><tbody>'+
 matrix.slice(0,40).map(c=>'<tr><td><b>'+esc(c.strategy_id)+'</b></td><td>'+esc(c.regime)+'</td><td>'+esc(c.liquidity)+'</td><td>'+esc(c.spread)+'</td><td>'+esc(c.order_size)+'</td><td>'+esc(c.closed??0)+(c.small_sample?'*':'')+'</td><td class="'+retClass(c.median_net_return_pct)+'">'+esc(c.median_net_return_pct==null?"—":obsPct(c.median_net_return_pct))+'</td><td>'+esc(c.positive_pct==null?"—":fmt(c.positive_pct,0)+"%")+'</td><td>'+esc(c.profit_factor==null?"—":fmt(c.profit_factor,2))+'</td><td>'+esc(c.median_return_drag_pct==null?"—":obsPct(c.median_return_drag_pct))+'</td><td>'+esc(c.median_round_trip_is_bps==null?"—":fmt(c.median_round_trip_is_bps,1)+"bp")+'</td></tr>').join("")+
 '</tbody></table></div><div class="sub" style="padding:7px 10px">* 완료표본 5건 미만 · capacity 근거로 사용하지 않음</div></div>':'';
 el.innerHTML=gate+capHtml+matrixHtml+'<div class="sub" style="padding:8px 10px">'+esc(p.note||"")+'</div>';
}

function renderAIAllocation(x){
 const el=document.getElementById("brokerAllocation");if(!el)return;
 const r=x||{},sum=r.summary||{},rows=r.allocations||[],rej=r.rejected||[],cons=r.constraints||{};
 const kpis=[
   ["가정자산",sum.account_equity_krw==null?"—":money(sum.account_equity_krw)],
   ["전체 Risk Cap",sum.total_risk_cap_krw==null?"—":money(sum.total_risk_cap_krw)],
   ["기존 Risk",sum.existing_risk_krw==null?"—":money(sum.existing_risk_krw)],
   ["신규 배정 Risk",sum.new_allocated_risk_krw==null?"—":money(sum.new_allocated_risk_krw)],
   ["Risk 사용률",sum.risk_utilization_pct==null?"—":fmt(sum.risk_utilization_pct,0)+"%"]
 ];
 const summary='<div class="allocation-summary">'+kpis.map(v=>'<div class="allocation-kpi"><div class="ak">'+esc(v[0])+'</div><div class="av">'+esc(v[1])+'</div></div>').join("")+'</div>';
 const pills='<div class="brief-list" style="padding:9px 10px">'+
   '<span class="pill">Single '+esc(cons.single_risk_cap_krw==null?"—":money(cons.single_risk_cap_krw))+'</span>'+
   '<span class="pill">Theme '+esc(cons.theme_risk_cap_krw==null?"—":money(cons.theme_risk_cap_krw))+'</span>'+
   '<span class="pill">Family '+esc(cons.family_risk_cap_krw==null?"—":money(cons.family_risk_cap_krw))+'</span>'+
   '<span class="pill">Position '+esc(cons.position_notional_cap_krw==null?"—":money(cons.position_notional_cap_krw))+'</span>'+
   '<span class="pill">Risk chunk '+esc(cons.risk_chunk_krw==null?"—":money(cons.risk_chunk_krw))+'</span>'+
   '</div>';
 let table='<div class="tblwrap"><table class="allocation-table"><thead><tr><th>종목</th><th>전략 / 테마</th><th>Evidence</th><th>Priority</th><th>Risk</th><th>Notional</th><th>수량</th><th>Stop</th><th>Capacity</th><th>사용률</th><th>최대 Corr</th><th>Corr 미확인</th></tr></thead><tbody>';
 table+=rows.length?rows.map(a=>{
   const evidence=a.evidence_scale>=.99?"VERIFIED":a.evidence_scale>=.3?"PENDING":"RESEARCH";
   return '<tr><td><b>'+esc(a.stock_name||a.stock_code)+'</b><div class="sub">'+esc(a.stock_code||"")+'</div></td>'+
    '<td>'+esc(a.strategy_id||"—")+'<div class="sub">'+esc(a.market_theme||"미분류")+' · '+esc(a.strategy_family||"")+'</div></td>'+
    '<td><span class="sp-state">'+esc(evidence)+'</span><div class="sub">'+esc(a.final_action||"")+'</div></td>'+
    '<td>'+esc(fmt((a.priority_score||0)*100,1))+'<div class="sub">연구 우선도</div></td>'+
    '<td><b>'+esc(money(a.allocated_risk_krw||0))+'</b></td><td>'+esc(money(a.allocated_notional_krw||0))+'</td>'+
    '<td>'+esc(a.shares??0)+'</td><td>'+esc(a.stop_pct==null?"—":fmt(a.stop_pct,2)+"%")+'</td>'+
    '<td>'+esc(a.capacity_krw==null?"—":money(a.capacity_krw))+'</td>'+
    '<td>'+esc(a.capacity_utilization_pct==null?"—":fmt(a.capacity_utilization_pct,0)+"%")+'</td>'+
    '<td>'+esc(a.max_positive_corr==null?"—":fmt(a.max_positive_corr,2))+'</td>'+
    '<td>'+esc(a.unknown_correlation_peers??0)+'</td></tr>';
 }).join(""):'<tr><td colspan="12" class="muted">현재 제약을 통과한 신규 Shadow 배분 없음</td></tr>';
 table+='</tbody></table></div>';
 let rejected='';
 if(rej.length){
   rejected='<details class="allocation-rejected"><summary>배분 제외 / 축소 사유 '+rej.length+'건</summary>'+
    rej.slice(0,15).map(v=>'<div class="allocation-reason"><span>'+esc(v.stock_name||v.stock_code||"후보")+'</span><b>'+esc((v.reasons||[]).join(", ")||"제약")+'</b></div>').join("")+'</details>';
 }
 el.innerHTML=summary+pills+table+rejected+'<div class="allocation-note">'+esc(r.note||"")+' · Priority는 기대수익률이 아니라 검증·신호·실행비용을 합친 연구 우선도입니다.</div>';
}

function renderShadowExecution(x){
 const el=document.getElementById("brokerShadow");if(!el)return;
 const r=x||{},sum=r.summary||{},rows=r.recent||[];
 const kpis=[
   ["진행",r.open_count??0],
   ["완전청산",r.closed_count??0],
   ["실행 거절",r.rejected_count??0],
   ["Risk 거절",r.risk_reject_count??0],
   ["중앙 Net",sum.median_net_return_pct==null?"—":obsPct(sum.median_net_return_pct)]
 ];
 const summary='<div class="shadow-summary">'+kpis.map(v=>'<div class="shadow-kpi"><div class="sk">'+esc(v[0])+'</div><div class="sv">'+esc(v[1])+'</div></div>').join("")+'</div>';
 const quality='<div class="brief-list" style="padding:9px 10px">'+
   '<span class="pill">BOOK_V2 '+esc(sum.book_coverage_pct==null?"—":fmt(sum.book_coverage_pct,0)+"%")+'</span>'+
   '<span class="pill">Entry IS '+esc(sum.median_entry_is_bps==null?"—":fmt(sum.median_entry_is_bps,1)+"bp")+'</span>'+
   '<span class="pill">Exit IS '+esc(sum.median_exit_is_bps==null?"—":fmt(sum.median_exit_is_bps,1)+"bp")+'</span>'+
   '<span class="pill">Round-trip IS '+esc(sum.median_round_trip_is_bps==null?"—":fmt(sum.median_round_trip_is_bps,1)+"bp")+'</span>'+
   '<span class="pill">Paper→Shadow drag '+esc(sum.median_return_drag_pct==null?"—":obsPct(sum.median_return_drag_pct))+'</span>'+
   '<span class="pill">체결률 '+esc(sum.median_fill_ratio_pct==null?"—":fmt(sum.median_fill_ratio_pct,0)+"%")+'</span>'+
   '<span class="pill">중앙 주문 '+esc(sum.median_notional_krw==null?"—":money(sum.median_notional_krw))+'</span>'+
   '</div>';
 let table='<div class="tblwrap"><table class="shadow-table"><thead><tr><th>종목</th><th>상태</th><th>모델</th><th>전략/테마</th><th>요청/체결</th><th>Risk</th><th>진입 Mid→Fill</th><th>Entry IS</th><th>청산 Mid→Fill</th><th>Exit IS</th><th>RT IS</th><th>Drag</th><th>Net</th></tr></thead><tbody>';
 table+=rows.length?rows.map(t=>{
   const sc=t.status==="CLOSED"?"closed":t.status==="CLOSED_PARTIAL_LIQUIDITY"?"partial":t.status==="REJECTED"?"rejected":"";
   const entry=(t.entry_arrival_mid_krw==null?(t.entry_ref_price_krw==null?"—":fmt(t.entry_ref_price_krw,0)):fmt(t.entry_arrival_mid_krw,0))+" → "+(t.entry_fill_price_krw==null?"—":fmt(t.entry_fill_price_krw,0));
   const exit=(t.exit_arrival_mid_krw==null?(t.exit_ref_price_krw==null?"—":fmt(t.exit_ref_price_krw,0)):fmt(t.exit_arrival_mid_krw,0))+" → "+(t.exit_fill_price_krw==null?"—":fmt(t.exit_fill_price_krw,0));
   const gate=t.risk_gate||{},blocks=gate.blockers||[];
   const riskText=(t.risk_at_entry_krw==null?"—":money(t.risk_at_entry_krw))+(blocks.length?(" · "+blocks.join(",")):"");
   return '<tr><td><b>'+esc(t.stock_name||t.name||t.stock_code||t.code)+'</b><div class="sub">'+esc(t.stock_code||t.code||"")+'</div></td>'+
    '<td><span class="shadow-status '+sc+'">'+esc(t.status||"")+'</span></td>'+
    '<td><b>'+esc(t.entry_model_mode||"—")+'</b><div class="sub">'+esc(t.entry_model_quality||"")+'</div></td>'+
    '<td>'+esc(t.strategy_id||"—")+'<div class="sub">'+esc(t.market_theme||"미분류")+' · '+esc(t.strategy_family||"")+'</div></td>'+
    '<td>'+esc((t.requested_shares??0)+" / "+(t.filled_shares??0))+'</td>'+
    '<td>'+esc(riskText)+'</td>'+
    '<td>'+esc(entry)+'</td><td>'+esc(t.entry_implementation_shortfall_bps==null?"—":fmt(t.entry_implementation_shortfall_bps,1)+"bp")+'</td>'+
    '<td>'+esc(exit)+'</td><td>'+esc(t.exit_implementation_shortfall_bps==null?"—":fmt(t.exit_implementation_shortfall_bps,1)+"bp")+'</td>'+
    '<td>'+esc(t.round_trip_is_bps==null?"—":fmt(t.round_trip_is_bps,1)+"bp")+'</td>'+
    '<td class="'+retClass(-(Number(t.return_drag_pct)||0))+'">'+esc(t.return_drag_pct==null?"—":obsPct(t.return_drag_pct))+'</td>'+
    '<td class="'+retClass(t.net_return_pct)+'">'+esc(t.net_return_pct==null?"—":obsPct(t.net_return_pct))+'</td></tr>';
 }).join(""):'<tr><td colspan="13" class="muted">Shadow v2 표본 축적 중</td></tr>';
 table+='</tbody></table></div>';
 const policy=rows[0]?.entry_model?.policy||{};
 const fees='commission '+esc(policy.commission_bps??0)+'bp · sell tax '+esc(policy.sell_tax_bps??0)+'bp';
 const ob=r.orderbook_feed||{};
 const bookHealth='호가수집 '+esc(ob.status||"미연결")+' · 대상 '+esc(ob.target_count??0)+' / 저장 '+esc(ob.saved_count??0);
 el.innerHTML=summary+quality+table+'<div class="shadow-note">'+bookHealth+' · '+esc(r.model_note||r.note||"")+' · '+fees+' · BOOK_V2와 PROXY_V1은 분리해 해석합니다.</div>';
}

function renderAIDailyReview(x){
 const el=document.getElementById("brokerDailyReview");if(!el)return;
 const r=x||{},d=r.decisions||{},states=d.states||{},p=r.paper||{},blocks=d.top_blockers||[],strategies=d.top_strategies||[];
 el.innerHTML='<div class="review-box"><b>오늘의 판단</b><div class="review-grid">'+
   [['판단',d.decisions??0],['PAPER',states.PAPER_ENTRY??0],['READY',states.READY??0],['BLOCKED',states.BLOCKED??0]].map(v=>'<div class="review-kpi"><div class="rk">'+esc(v[0])+'</div><div class="rv">'+esc(v[1])+'</div></div>').join("")+
   '</div><div class="review-lines">'+(blocks.length?blocks.map(b=>'<div class="review-line"><span>'+esc(b.desk)+' 차단</span><b>'+esc(b.count)+'</b></div>').join(""):'<div class="review-line"><span>차단 패턴</span><b>표본 대기</b></div>')+'</div></div>'+
   '<div class="review-box"><b>Paper 결과 · 전략 귀속</b><div class="review-grid">'+
   [['진입',p.opened??0],['완료',p.closed??0],['중앙',p.median_return_pct==null?"—":obsPct(p.median_return_pct)],['양(+)',p.positive_pct==null?"—":fmt(p.positive_pct,0)+"%"]].map(v=>'<div class="review-kpi"><div class="rk">'+esc(v[0])+'</div><div class="rv">'+esc(v[1])+'</div></div>').join("")+
   '</div><div class="review-lines">'+(strategies.length?strategies.map(s=>'<div class="review-line"><span>'+esc(s.strategy_id)+'</span><b>'+esc(s.count)+'</b></div>').join(""):'<div class="review-line"><span>전략 이력</span><b>축적 중</b></div>')+
   '<div class="review-line"><span>Paper Feedback</span><b>'+esc(r.feedback_label||r.feedback_state||"대기")+'</b></div></div></div>';
}
function renderAIBrokerage(broker){
 const b=broker||{},reg=b.registry||{},candidates=b.candidates||[];
 const regEl=document.getElementById("brokerRegistry"),candEl=document.getElementById("brokerCandidates");
 const modeEl=document.getElementById("brokerMode"),statusEl=document.getElementById("brokerStatus");
 if(modeEl)modeEl.textContent=b.paper_only===false?"LIVE ENABLED":"PAPER ONLY";
 if(statusEl)statusEl.textContent=(b.status||"대기")+" · "+(b.note||"실계좌 주문 경로 없음");
 if(regEl){
   const order=[["DESIGN","설계"],["PAPER","가상검증"],["ACTIVE","활성"],["DISABLED","중지"]];
   const total=order.reduce((a,x)=>a+Number(reg[x[0]]||0),0);
   regEl.innerHTML=order.map(x=>'<div class="broker-reg"><div class="br-k">'+esc(x[1])+' · '+esc(x[0])+'</div><div class="br-v">'+esc(reg[x[0]]??0)+'</div><div class="sub">'+(x[0]==="DESIGN"?"조건 정의·검증 전":x[0]==="PAPER"?"forward-test 중":x[0]==="ACTIVE"?"승격 기준 통과":"운영 제외")+'</div></div>').join("")+
     '<div class="broker-reg" style="grid-column:1/-1"><div class="br-k">REGISTRY TOTAL</div><div class="br-v">'+esc(total)+'</div><div class="sub">슬롯 수와 검증 완료 수를 구분해 표시합니다.</div></div>';
 }
 if(!candEl)return;
 if(!candidates.length){
   candEl.innerHTML='<div class="panel pad muted" style="grid-column:1/-1">현재 candidate tracker에서 6-Desk 평가 대상으로 유지 중인 종목이 없습니다.</div>';
   return;
 }
 const labels={market:"Market 시장",catalyst:"Catalyst 재료",flow:"Flow 수급",technical:"Technical 차트",strategy:"Strategy 전략",risk:"Risk 리스크"};
 const states={PAPER_ENTRY:"PAPER 진입",READY:"READY",WATCH:"WATCH",BLOCKED:"BLOCKED",IGNORE:"IGNORE"};
 candEl.innerHTML=candidates.slice(0,8).map(x=>{
   const cls=x.state==="PAPER_ENTRY"?"entry":x.state==="READY"?"ready":x.state==="WATCH"?"watch":x.state==="BLOCKED"?"blocked":"";
   const st=x.selected_strategy||{};
   const desks=(x.desks||[]).map(d=>{
     const raw=Number(d.score||0),bar=Math.max(0,Math.min(100,(raw+1)*50));
     const signed=(raw>0?"+":"")+Math.round(raw*100);
     return '<div class="broker-deskline"><b>'+esc(labels[d.desk]||d.desk)+'</b><div class="broker-bar"><i style="width:'+bar.toFixed(0)+'%"></i></div><span>'+esc(signed)+'</span></div>';
   }).join("");
   const blocks=(x.blockers||[]).slice(0,3);
   return '<article class="broker-card '+cls+'"><div class="broker-top"><div><div class="broker-name">'+esc(x.stock_name||x.stock_code)+'</div><div class="sub">'+esc(x.stock_code||"")+'</div><span class="broker-state">'+esc(states[x.state]||x.state)+'</span></div><div><div class="broker-conv">'+esc(fmt(x.conviction,0))+'</div><div class="sub">conviction / 100</div></div></div>'+
     '<div class="broker-strategy"><b>'+(st.strategy_id?esc(st.strategy_id+" · "+st.name):"선택 전략 없음")+'</b>'+(st.fit_score!=null?'<div class="sub">family '+esc(st.family||"-")+' · fit '+esc(fmt(st.fit_score,0))+' · '+esc(st.lifecycle||"")+'</div>':'')+'</div>'+
     '<div style="margin-top:7px">'+desks+'</div>'+
     (blocks.length?'<div class="broker-block"><b>VETO / BLOCKER</b><br>'+blocks.map(esc).join("<br>")+'</div>':'')+
     '<div class="broker-foot">실거래 주문 아님 · 판단 근거와 거부 사유를 먼저 기록</div></article>';
 }).join("");
}

function renderPaperLab(lab){
 const x=lab||{},sum=x.summary||{},open=x.open||[],closed=x.recent_closed||[];
 const kpi=[
  ['진행 중',String(open.length)+'건',''],
  ['30일 완료',String(sum.closed??0)+'건',''],
  ['중앙 관찰수익',sum.median_return_pct==null?'—':obsPct(sum.median_return_pct),retClass(sum.median_return_pct)],
  ['양(+) 관측',sum.positive_pct==null?'—':fmt(sum.positive_pct,0)+'%','']
 ];
 const head='<div class="paper-head"><div><b>Paper Lab</b><div class="sub">관찰도 70+ 유지 → 가상 진입 · 후보탈락/차트훼손/고점경계/30분 → 가상 청산</div></div><span class="paper-badge">'+esc(x.status||'대기')+' · 실계좌 미연결</span></div>';
 const summary='<div class="paper-summary">'+kpi.map(v=>'<div class="paper-kpi"><div class="pk">'+esc(v[0])+'</div><div class="pv '+v[2]+'">'+esc(v[1])+'</div></div>').join('')+'</div>';
 let positions='<div class="paper-open-grid">';
 if(!open.length)positions+='<div class="muted" style="grid-column:1/-1;padding:8px">현재 가상 진입 중인 종목 없음 · 조건 충족 후보를 관찰 중입니다.</div>';
 else positions+=open.slice(0,5).map(t=>{
   const ret=Number(t.return_pct),mfe=Number(t.mfe_pct),mae=Number(t.mae_pct);
   const reasons=(t.entry_reason||[]).slice(0,3).join(' · ');
   return '<article class="paper-position"><div class="hc-top"><div><div class="pp-name">'+esc(t.name||t.code)+'</div><div class="pp-meta">'+esc(t.market_theme||'테마 미확인')+' · '+esc(t.primary_type||'관찰')+'</div></div><div class="pp-ret '+retClass(ret)+'">'+esc(obsPct(ret))+'</div></div>'+
    '<div class="pp-prices">진입 '+esc(t.entry_price_krw==null?'—':fmt(t.entry_price_krw,0))+' → 현재 '+esc(t.mark_price_krw==null?'—':fmt(t.mark_price_krw,0))+'</div>'+
    '<div class="pp-meta">'+esc(t.opened_at?new Date(t.opened_at).toLocaleTimeString("ko-KR"):'')+' · 진입 관찰도 '+esc(t.entry_score??'-')+'</div>'+
    '<div class="paper-path"><span class="pill">MFE '+esc(obsPct(mfe))+'</span><span class="pill">MAE '+esc(obsPct(mae))+'</span></div>'+
    '<div class="paper-reason">'+esc(reasons||'가상진입 근거 기록 대기')+'</div></article>';
 }).join('');
 positions+='</div>';
 const rows=closed.slice(0,10).map(t=>'<tr><td><b>'+esc(t.name||t.code)+'</b><div class="sub">'+esc(t.primary_type||'')+'</div></td><td>'+esc(t.opened_at?new Date(t.opened_at).toLocaleTimeString("ko-KR"):'—')+'</td><td>'+esc(t.closed_at?new Date(t.closed_at).toLocaleTimeString("ko-KR"):'—')+'</td><td class="'+retClass(t.return_pct)+'">'+esc(t.return_pct==null?'자료없음':obsPct(t.return_pct))+'</td><td>'+esc(obsPct(t.mfe_pct))+'</td><td>'+esc(obsPct(t.mae_pct))+'</td><td class="left">'+esc(t.exit_reason||'—')+'</td></tr>').join('');
 const recent='<details class="paper-closed"><summary>최근 가상 청산 '+closed.length+'건 보기'+(sum.small_sample?' · 소표본':'')+'</summary><div class="paper-table-wrap"><table class="paper-table"><thead><tr><th>종목</th><th>진입</th><th>청산</th><th>관찰수익</th><th>MFE</th><th>MAE</th><th class="left">청산 이유</th></tr></thead><tbody>'+(rows||'<tr><td colspan="7" class="muted">아직 완료된 가상매매가 없습니다.</td></tr>')+'</tbody></table></div></details>';
 return head+summary+positions+recent+'<div class="sub" style="padding:8px 12px;border-top:1px solid #edf1f6">수수료·세금·슬리피지·호가체결을 반영하지 않은 규칙 검증용 가격경로입니다. 실제 주문이나 매매 지시가 아닙니다.</div>';
}
function renderPaperFeedback(fb){
 const root=fb||{},p=root.payload||{},o=p.overall||{},checks=p.checks||[],types=p.types||[],bands=p.score_bands||[];
 const state=p.state||root.status||"SAMPLE_BUILDING",label=p.label||"표본 축적";
 const stateClass=state==="STABLE"?"pf-keep":state==="REVIEW"?"pf-review":"pf-sample";
 const kpis=[
   ["완료 표본",String(o.n??0)+"건"],
   ["중앙 관찰수익",o.median_return_pct==null?"—":obsPct(o.median_return_pct)],
   ["양(+) 관측",o.positive_pct==null?"—":fmt(o.positive_pct,0)+"%"],
   ["되돌림",o.giveback_pct==null?"—":fmt(o.giveback_pct,0)+"%"],
   ["초기 실패",o.immediate_failure_pct==null?"—":fmt(o.immediate_failure_pct,0)+"%"]
 ];
 const head='<div class="pf-head"><div><b>Paper Lab 자동 피드백</b><div class="sub">결과를 분석하지만 실시간 규칙은 자동 변경하지 않습니다.</div></div><span class="pf-state '+stateClass+'">'+esc(label)+'</span></div>';
 const overall='<div class="pf-overall">'+kpis.map(x=>'<div class="pf-kpi"><div class="k">'+esc(x[0])+'</div><div class="v">'+esc(x[1])+'</div></div>').join('')+'</div>';
 let checkHtml='<div class="pf-box"><div class="pf-box-head">규칙 검증</div>';
 if(!checks.length)checkHtml+='<div class="pf-check"><p>피드백 계산 대기</p></div>';
 else checkHtml+=checks.slice(0,5).map(c=>{
   const cls=c.status==="KEEP"?"pf-keep":c.status==="REVIEW_CANDIDATE"?"pf-review":"pf-sample";
   return '<div class="pf-check"><div class="pf-check-title"><span>'+esc(c.rule||"규칙")+'</span><span class="pf-state '+cls+'">'+esc(c.label||c.status||"")+'</span></div><p>'+esc(c.message||"")+'</p></div>';
 }).join('');
 checkHtml+='</div>';
 let typeHtml='<div class="pf-box"><div class="pf-box-head">후보 유형별 · n / 중앙값 / 양(+)비율</div>';
 if(!types.length)typeHtml+='<div class="pf-check"><p>유형별 표본 축적 중</p></div>';
 else typeHtml+=types.slice(0,6).map(t=>'<div class="pf-type"><b>'+esc(t.key)+'</b><span>n='+esc(t.n)+'</span><span class="'+retClass(t.median_return_pct)+'">'+esc(t.median_return_pct==null?'—':obsPct(t.median_return_pct))+'</span><span>'+esc(t.positive_pct==null?'—':fmt(t.positive_pct,0)+'%')+'</span></div>').join('');
 if(bands.length){
   typeHtml+='<div class="pf-box-head">진입 관찰도 구간</div>'+bands.map(b=>'<div class="pf-band"><span>'+esc(b.key)+' · n='+esc(b.n)+'</span><span class="'+retClass(b.median_return_pct)+'">'+esc(b.median_return_pct==null?'—':obsPct(b.median_return_pct))+'</span></div>').join('');
 }
 typeHtml+='</div>';
 return head+overall+'<div class="pf-grid">'+checkHtml+typeHtml+'</div><div class="pf-note">'+esc(p.note||root.note||"규칙 변경은 수동 검토 후 별도 버전으로만 적용")+'</div>';
}
function evidence(c){
 let out="";
 (c?.dart||[]).slice(0,5).forEach(d=>{out+='<div class="evidence"><b>DART · '+esc(d.category||"공시")+'</b><p>'+esc(d.report_nm||"")+'</p><div class="links">'+(d.link?'<a href="'+esc(d.link)+'" target="_blank">공시 열기</a>':"")+'</div></div>'});
 (c?.external_news||[]).slice(0,5).forEach(n=>{out+='<div class="evidence"><b>'+esc(n.source||"뉴스")+'</b><p>'+esc(n.title||"")+'</p><div class="links"><a href="'+esc(n.link)+'" target="_blank">기사 열기</a></div></div>'});
 (c?.items||[]).slice(0,4).forEach(i=>{out+='<div class="evidence"><b>'+esc(i.channel||"Telegram")+'</b><p>'+esc(i.text||"")+'</p><div class="links">'+(i.telegram_url?'<a href="'+esc(i.telegram_url)+'" target="_blank">원문</a>':"")+'</div></div>'});
 return out;
}
function materialCards(list){
 return (list||[]).slice(0,30).map(x=>{
   const d=x.digest||{},c=x.catalyst||{};
   return '<article class="material-card"><div class="material-top"><h3>'+esc(x.name||x.code)+'</h3><span class="'+klass(x.change_rate)+'"><b>'+esc(rate(x.change_rate))+'</b></span></div><div class="sub">조회 #'+esc(x.query_rank??"-")+' · 대금 #'+esc(x.trade_rank??"-")+' · '+esc(x.sector||"미분류")+'</div><div class="material-summary">'+esc(d.summary||"직접 재료 미확인")+'</div><div class="legend"><span class="pill">'+esc(d.assessment||"미확인")+'</span><span class="pill">'+esc(d.newness||"")+'</span><span class="pill">'+esc(x.flow_state||"관찰")+'</span></div><div class="material-why"><b>'+esc(d.market_response||"")+'</b><div style="margin-top:4px">'+esc(d.synthesis||d.interpretation||"추가 확인 필요")+'</div><div class="sub" style="margin-top:4px">'+esc(d.quality_note||"")+'</div></div><details><summary>근거 원문·기사 보기</summary>'+evidence(c)+'</details><div class="fb"><button onclick="sendFeedback(\'material\',\''+esc(x.code)+'\',\''+esc(d.assessment||"")+'\',\'correct\',this)">재료 맞음</button><button onclick="sendFeedback(\'material\',\''+esc(x.code)+'\',\''+esc(d.assessment||"")+'\',\'wrong\',this)">재료 아님</button></div></article>';
 }).join("")||'<div class="panel pad muted">재료 데이터 대기 중</div>';
}
function mimosaCards(list){
 return (list||[]).slice(0,30).map(x=>{
   const reasons=(x.reasons||[]).map(r=>'<span class="pill">'+esc(r)+'</span>').join("");
   return '<div class="m-card"><div class="m-head"><div><b>'+esc(x.name||x.code)+'</b><div class="sub">조회 #'+esc(x.query_rank??"-")+' · 대금 #'+esc(x.trade_rank??"-")+'</div></div><div class="score">'+esc(Math.round(Number(x.score||0)))+'</div></div><div class="m-state">'+esc(x.state_ko||"차트 데이터 대기")+'</div><div class="sub">'+esc(x.minute_trend||"분봉 미확인")+' · '+esc(x.daily_context||"일봉 미확인")+'</div><div class="reason">'+reasons+'</div><div class="fb"><button onclick="sendFeedback(\'mimosa\',\''+esc(x.code)+'\',\''+esc(x.state||x.state_ko||"")+'\',\'correct\',this)">판독 맞음</button><button onclick="sendFeedback(\'mimosa\',\''+esc(x.code)+'\',\''+esc(x.state||x.state_ko||"")+'\',\'wrong\',this)">판독 아님</button></div></div>';
 }).join("")||'<div class="panel pad muted">미모사 차트 데이터 대기 중</div>';
}

function renderEtfRows(rows){
 return (rows||[]).slice(0,30).map(x=>
   '<tr><td>'+esc(x.trade_rank??"-")+'</td><td class="left"><b>'+esc(x.name||x.code)+'</b><div class="sub">'+esc(x.code||"")+'</div></td><td class="'+klass(x.change_rate)+'">'+esc(rate(x.change_rate))+'</td><td>'+esc(money(x.trade_value_krw))+'</td><td class="left"><span class="pill">ETF/ETN 분리</span></td></tr>'
 ).join("")||'<tr><td colspan="5" class="muted">ETF/ETN 데이터 없음</td></tr>';
}


function sparkChart(rows,key,labelMode){
 const pts=(rows||[]).filter(x=>x[key]!=null);
 if(pts.length<2)return '<div class="muted" style="padding:70px 10px;text-align:center">차트 데이터 대기</div>';
 const vals=pts.map(x=>Number(x[key])); const min=Math.min(...vals),max=Math.max(...vals),span=(max-min)||1;
 const W=600,H=210,P=18;
 const xy=vals.map((v,i)=>[(P+(W-2*P)*i/(vals.length-1)),(P+(H-2*P)*(1-(v-min)/span))]);
 const path=xy.map((p,i)=>(i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)).join(' ');
 const first=vals[0],last=vals[vals.length-1],chg=first?((last/first-1)*100):0;
 return '<svg class="svgchart" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+
   '<line x1="'+P+'" y1="'+P+'" x2="'+P+'" y2="'+(H-P)+'" stroke="#dce3ee"/>'+
   '<line x1="'+P+'" y1="'+(H-P)+'" x2="'+(W-P)+'" y2="'+(H-P)+'" stroke="#dce3ee"/>'+
   '<path d="'+path+'" fill="none" stroke="#345c9c" stroke-width="2.2" vector-effect="non-scaling-stroke"/>'+
   '<text x="'+(P+3)+'" y="'+(P+11)+'" font-size="10" fill="#6f7c90">'+max.toFixed(2)+'</text>'+
   '<text x="'+(P+3)+'" y="'+(H-P-5)+'" font-size="10" fill="#6f7c90">'+min.toFixed(2)+'</text>'+
   '<text x="'+(W-P-90)+'" y="'+(P+11)+'" font-size="11" fill="'+(chg>=0?'#e25555':'#4577d4')+'">'+(chg>=0?'+':'')+chg.toFixed(2)+'%</text>'+
   '</svg>';
}
function lastValue(rows,key){
 const p=(rows||[]).filter(x=>x[key]!=null); if(!p.length)return "-";
 const v=Number(p[p.length-1][key]); const first=Number(p[0][key]); const chg=first?((v/first-1)*100):0;
 return '<b>'+fmt(v,2)+'</b> <span class="'+klass(chg)+'">'+(chg>=0?'+':'')+chg.toFixed(2)+'%</span>';
}
function strategyCards(list,kind){
 const rows=(list||[]).filter(x=>!(x.state||"").endsWith("_NO")).slice(0,18);
 if(!rows.length)return '<div class="panel pad muted">현재 조건에 가까운 종목이 없습니다.</div>';
 return rows.map(x=>{
   const rs=(x.reasons||[]).map(r=>'<span class="pill">'+esc(r)+'</span>').join("");
   const m=x.metrics||{};
   let metric="";
   if(kind==="close")metric='대금 #'+esc(m.trade_rank??"-")+' · '+esc(m.nxt_enabled?"NXT 가능":"KRX형")+(m.close_location!=null?' · 종가위치 '+(Number(m.close_location)*100).toFixed(0)+'%':'');
   if(kind==="oversold")metric='고점대비 '+esc(m.drawdown_pct==null?"-":Number(m.drawdown_pct).toFixed(1)+"%")+' · 조회 #'+esc(m.query_rank??"-")+' · 대금 #'+esc(m.trade_rank??"-");
   if(kind==="falling")metric='당일고점대비 '+esc(m.day_drawdown_pct==null?"-":Number(m.day_drawdown_pct).toFixed(1)+"%")+' · 선행상승 '+esc(m.prior_run_pct==null?"-":Number(m.prior_run_pct).toFixed(1)+"%");
   return '<article class="strategy-card"><div class="material-top"><h3>'+esc(x.name||x.code)+'</h3><span class="strategy-score">'+Math.round(Number(x.score||0))+'</span></div><div class="sub">조회 #'+esc(x.query_rank??"-")+' · 대금 #'+esc(x.trade_rank??"-")+' · '+esc(x.sector||"미분류")+'</div><div class="m-state">'+esc(x.state_ko||x.state)+'</div><div class="sub" style="margin-top:3px">'+metric+'</div><div class="reason">'+rs+'</div><div class="strategy-note">'+esc(x.source_note||"")+'</div><div class="fb"><button onclick="sendFeedback(\'mimosa\',\''+esc(x.code)+'\',\''+esc(x.state||"")+'\',\'correct\',this)">판독 맞음</button><button onclick="sendFeedback(\'mimosa\',\''+esc(x.code)+'\',\''+esc(x.state||"")+'\',\'wrong\',this)">판독 아님</button></div></article>';
 }).join("");
}


function researchCards(rows){
 if(!(rows||[]).length)return '<div class="panel pad muted">현재 Research Agent 트리거가 없습니다.</div>';
 return (rows||[]).map(x=>{
   const triggers=(x.triggers||[]).map(t=>'<span class="pill">'+esc(t)+'</span>').join("");
   const evidence=(x.evidence||[]).slice(0,5).map(e=>'<div class="evidence"><b>'+esc(e.source||e.type||"근거")+'</b><p>'+esc(e.title||"")+'</p>'+(e.link?'<a href="'+esc(e.link)+'" target="_blank">원문</a>':"")+'</div>').join("");
   return '<article class="research-card '+priorityClass(x.priority)+'"><div class="material-top"><div><h3>'+esc(x.name||x.code)+'</h3><div class="sub">'+esc(x.created_at?new Date(x.created_at).toLocaleString("ko-KR"):"")+'</div></div><div class="priority">'+esc(x.priority)+'</div></div><div class="legend" style="margin-top:7px">'+triggers+(x.deep_research_needed?'<span class="pill deep">심층조사 필요</span>':'')+'</div><div class="material-summary">'+esc(x.headline||"")+'</div><div class="material-why">'+esc(x.summary||"")+'</div><details><summary>수집 근거 보기 · '+esc((x.evidence||[]).length)+'건</summary>'+evidence+'</details></article>';
 }).join("");
}


function priorityClass(p){p=Number(p||0);return p>=80?"p-high":p>=60?"p-mid":"p-low";}
function deepResearchCards(rows){
 if(!(rows||[]).length)return '<div class="panel pad muted">아직 멀티에이전트 종합 리포트가 없습니다.</div>';
 return (rows||[]).map(x=>{
   const ev=x.evidence_summary||{}, risks=(x.risk_flags||[]).map(r=>'<span class="pill risk-pill">'+esc(r)+'</span>').join("");
   const agents=['수급','공시','뉴스','Telegram','섹터','미모사','시장'].map(a=>'<span class="pill agent-pill">'+a+'</span>').join("");
   return '<article class="deep-card"><div class="deep-head"><div><div class="sub">Priority '+esc(x.priority)+' · '+esc(x.report_version||"")+'</div><h3 style="margin:3px 0 0;font-size:16px">'+esc(x.headline||x.name||x.code)+'</h3></div><div class="confidence">'+esc(Math.round(Number(x.confidence||0)))+'</div></div>'+
   '<div class="legend" style="margin:9px 0">'+agents+risks+'</div>'+
   '<div class="deep-row"><div class="deep-key">왜 지금?</div><div>'+esc(x.why_now||"-")+'</div></div>'+
   '<div class="deep-row"><div class="deep-key">재료</div><div>'+esc(x.catalyst_summary||"-")+'</div></div>'+
   '<div class="deep-row"><div class="deep-key">시장 반응</div><div>'+esc(x.market_response||"-")+'</div></div>'+
   '<div class="deep-row"><div class="deep-key">섹터 확인</div><div>'+esc(x.sector_confirmation||"-")+'</div></div>'+
   '<div class="deep-row"><div class="deep-key">미모사</div><div>'+esc(x.mimosa_summary||"-")+'</div></div>'+
   '<div class="sub" style="margin-top:8px">근거 · DART '+esc(ev.dart??0)+' · 뉴스 '+esc(ev.news??0)+' · Telegram '+esc(ev.telegram??0)+' · 동종 '+esc(ev.sector_peers??0)+'</div></article>';
 }).join("");
}

function render(d){
 DATA=d;
 document.getElementById("stamp").textContent=new Date(d.generated_at).toLocaleString("ko-KR");
 const hb=d.home_brief||{};const hbEl=document.getElementById("homeBrief");if(hbEl)hbEl.innerHTML='<b>시장 핵심</b><span>'+esc(hb.headline||"시장 관측 축적 중")+'</span>';
 const label=d.regime.stable_label||d.regime.candidate_label||d.regime.status;
 document.getElementById("regime").textContent=label;
 document.getElementById("regimeSub").textContent=d.regime.note||"";
 const snap=d.market_snapshot||{};
 const liveText=snap.is_live?"LIVE":(snap.session_label||"장외");
 document.getElementById("kiwoom").textContent=liveText;
 document.getElementById("kiwoomSub").textContent="Kiwoom "+(d.system.kiwoom.status||"미연결")+(snap.time?" · "+new Date(snap.time).toLocaleTimeString("ko-KR"):"")+(snap.stale?" · 지연":"");
 const ms=d.material_stats||{};
 document.getElementById("newsStatus").textContent="직접 "+(ms.direct||0)+" · 테마 "+(ms.sector||0);
 const ds=d.system.dartfeed||{};
 document.getElementById("newsSub").textContent="확산 "+(ms.spreading||0)+" · 약한언급 "+(ms.weak||0)+" · DART "+(ds.status||"미연결")+" · Telegram "+(d.system.telegram.count_24h||0).toLocaleString()+"건";
 document.getElementById("turnover").textContent=d.regime_metrics?.rank_turnover_5m==null?"-":pct(d.regime_metrics.rank_turnover_5m);
 const homeTop=(d.query_ranking||[]).slice(0,12);
 const topWarnCount=homeTop.filter(x=>x.reversal_signal?.kind==="TOP_WARNING").length;
 const bottomWatchCount=homeTop.filter(x=>x.reversal_signal?.kind==="BOTTOM_WATCH").length;
 document.getElementById("mimosaStatus").textContent="고점 "+topWarnCount+" · 바닥 "+bottomWatchCount;
 const re=d.system.research||{};
 const rsEl=document.getElementById("researchStatus");
 if(rsEl)rsEl.textContent="Research Engine "+(re.status||"미연결")+(re.note?" · "+re.note:"");
 const dre=d.system.deepresearch||{};
 const drEl=document.getElementById("deepResearchStatus");
 if(drEl)drEl.textContent="Deep Research Engine "+(dre.status||"미연결")+(dre.note?" · "+dre.note:"");
 document.getElementById("mimosaSub").textContent="미모사 "+(d.system.mimosa?.status||"미연결")+" · 차트 "+(d.system.chartfeed?.status||"미연결");
 document.getElementById("analysis").innerHTML=(d.analysis?.lines||[]).map(x=>'<div class="analysis-line">'+esc(x)+'</div>').join("")||'<span class="muted">시장 분석 대기</span>';
 const sig=[];
 const strongestTheme=[...(d.sector_rankings||[])].sort((a,b)=>Number(b.theme_strength||0)-Number(a.theme_strength||0))[0];
 if(strongestTheme)sig.push("테마강도 "+strongestTheme.name+" "+(strongestTheme.theme_strength??"-"));
 if((d.sector_rankings||[])[0])sig.push("조회집중 "+d.sector_rankings[0].name);
 const noMat=(d.query_ranking||[]).filter(x=>x.flow_state==="돈 선행 / 재료 미확인").length;
 if(noMat)sig.push("돈선행 "+noMat+"종목");
 if((d.material_stats?.direct||0)>0)sig.push("직접재료 "+d.material_stats.direct+"종목");
 if((d.material_stats?.spreading||0)>0)sig.push("확산 "+d.material_stats.spreading+"종목");
 if(topWarnCount)sig.push("고점경계 "+topWarnCount+"종목");
 if(bottomWatchCount)sig.push("바닥감시 "+bottomWatchCount+"종목");
 if(d.regime_metrics?.rank_turnover_5m!=null)sig.push("교체율 "+pct(d.regime_metrics.rank_turnover_5m));
 document.getElementById("quickSignals").innerHTML=sig.map(x=>'<span class="pill">'+esc(x)+'</span>').join("");
 const homeThemes=[...(d.sector_rankings||[])].sort((a,b)=>(Number(b.theme_strength||0)-Number(a.theme_strength||0))||(Number(b.recent_turnover_krw||0)-Number(a.recent_turnover_krw||0)));
 const desk=d.leader_desk||{};
 document.getElementById("homeLeaderSectors").innerHTML=renderLeaderSectors(desk);
 document.getElementById("homeStrongTurnover").innerHTML=renderStrongTurnover(desk);
 document.getElementById("homeLeaderCalendar").innerHTML=renderLeaderCalendar(desk.calendar||{});
 document.getElementById("homeCalendarMeta").textContent=(desk.calendar?.observed_days??0)+"일 이력 · 저장 데이터 기준";
 document.getElementById("homeSectors").innerHTML=sectorCards(homeThemes,4,true);
 document.getElementById("sectorBoard").innerHTML=sectorCards(d.sector_rankings,20,false);
 document.getElementById("homeMaterialLegend").innerHTML=renderMaterialLegend();
 document.getElementById("homeSectorMix").innerHTML=renderSectorMix(d.query_ranking);
 document.getElementById("homeStocks").innerHTML=renderHomeStocks(d.query_ranking);
 document.getElementById("homeCandidates").innerHTML=renderHomeCandidates(d.home_candidates);
 document.getElementById("homePaperLab").innerHTML=renderPaperLab(d.paper_lab);
 document.getElementById("homePaperFeedback").innerHTML=renderPaperFeedback(d.paper_feedback);
 renderAIBrokerage(d.ai_brokerage);
 renderAIMorningBrief(d.ai_morning_brief);
 renderAIStrategyPerformance(d.ai_strategy_performance);
 renderAICapacity(d.ai_capacity);
 renderAIAllocation(d.ai_allocation);
 renderShadowExecution(d.shadow_execution);
 renderAIDailyReview(d.ai_daily_review);
 document.getElementById("queryRows").innerHTML=(d.query_ranking||[]).map(x=>stockRow(x,"query")).join("")||'<tr><td colspan="10">데이터 대기</td></tr>';
 document.getElementById("tradeRows").innerHTML=(d.trade_ranking||[]).map(x=>stockRow(x,"trade")).join("")||'<tr><td colspan="10">데이터 대기</td></tr>';
 document.getElementById("etfTradeRows").innerHTML=renderEtfRows(d.etf_trade_ranking);
 document.getElementById("officialSectors").innerHTML=(d.sectors||[]).map(x=>'<tr><td class="left"><b>'+esc(x.name)+'</b></td><td class="'+klass(x.change_rate)+'">'+esc(rate(x.change_rate))+'</td><td>'+esc(money(x.trade_value_krw))+'</td><td>'+esc(x.rising??"-")+'</td><td>'+esc(x.falling??"-")+'</td></tr>').join("");
 document.getElementById("materials").innerHTML=materialCards(d.materials);
 document.getElementById("researchCards").innerHTML=researchCards(d.research_rows);
 document.getElementById("deepResearchCards").innerHTML=deepResearchCards(d.deep_reports);
 document.getElementById("mimosaCards").innerHTML=mimosaCards(d.mimosa_rows);
 const ix=d.index_charts||{};
 const kp=ix.KOSPI||{}, kq=ix.KOSDAQ||{};
 document.getElementById("kospiIntra").innerHTML=sparkChart(kp.intraday,"close","time");
 document.getElementById("kosdaqIntra").innerHTML=sparkChart(kq.intraday,"close","time");
 document.getElementById("kospiDaily").innerHTML=sparkChart(kp.daily,"close","date");
 document.getElementById("kosdaqDaily").innerHTML=sparkChart(kq.daily,"close","date");
 document.getElementById("kospiIntraLast").innerHTML=lastValue(kp.intraday,"close");
 document.getElementById("kosdaqIntraLast").innerHTML=lastValue(kq.intraday,"close");
 document.getElementById("kospiDailyLast").innerHTML=lastValue(kp.daily,"close");
 document.getElementById("kosdaqDailyLast").innerHTML=lastValue(kq.daily,"close");
 const msig=d.mimosa_strategies||{};
 document.getElementById("closeBetCards").innerHTML=strategyCards(msig.CLOSE_BET,"close");
 document.getElementById("oversoldCards").innerHTML=strategyCards(msig.OVERSOLD,"oversold");
 document.getElementById("fallingCards").innerHTML=strategyCards(msig.FALLING_STOCK,"falling");
}
async function load(){
 if(!token){document.getElementById("regime").textContent="접속키 필요";return;}
 try{const r=await fetch("/api/dashboard",{headers:{"x-dashboard-token":token}});if(!r.ok)throw new Error("HTTP "+r.status);render(await r.json());}
 catch(e){document.getElementById("kiwoom").textContent="연결 오류";console.error(e);}
}
load();setInterval(load,10000);
</script></body></html>"""
