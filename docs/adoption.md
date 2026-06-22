# Adoption

Verel and AgentVision ship and version independently, but grow together. Live-ish snapshot of real PyPI download adoption (the trend is from pypistats; the country map from the BigQuery public dataset).

<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/jsvectormap@1.5.3/dist/css/jsvectormap.min.css">
<style>
.adopt{--l:#262633;--m:#a6a6c4;--ac:#8b7cff;--ac2:#5ad1e6}
.adopt .box{background:#0b0b12;border:1px solid var(--l);border-radius:14px;padding:16px;margin:14px 0}
.adopt h3{margin:0 0 8px;font-size:16px}
.adopt .sub{color:var(--m);font-size:13px;margin:-2px 0 10px}
.adopt #aTrend{height:300px}
.adopt #aMap{height:460px}
.adopt .tabs{display:flex;gap:8px;justify-content:center;margin-bottom:10px}
.adopt .tab{background:#15151f;border:1px solid var(--l);color:var(--m);border-radius:9px;padding:6px 16px;font-weight:600;font-size:13px;cursor:pointer}
.adopt .tab.on{border-color:var(--ac);color:#fff}
.adopt .jvm-tooltip{background:#14141f!important;border:1px solid var(--l)!important;color:#eceaf7!important;border-radius:8px!important;padding:6px 10px!important}
</style>
<div class="adopt">
  <div class="box"><h3>📈 Downloads over time</h3><div class="sub">Daily PyPI downloads (no mirrors) &middot; verel ~2,425 in-window</div>
    <div id="aTrend"></div></div>
  <div class="box"><h3>🌍 Where it's installed</h3><div class="sub">Real PyPI downloads by country &mdash; last 30 days via BigQuery (snapshot 2026-06-22). Hover a country for its count.</div>
    <div class="tabs"><button class="tab on" data-p="verel">Verel</button><button class="tab" data-p="agentvision">AgentVision</button></div><div id="aMap"></div></div>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/jsvectormap@1.5.3/dist/js/jsvectormap.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/jsvectormap@1.5.3/dist/maps/world.js"></script>
<script>window.ADOPT={"trend": {"labels": ["06-18", "06-19", "06-20", "06-21"], "datasets": {"verel": [222, 1347, 112, 744], "agentvision": [228, 716, 89, 48]}, "labelmap": {"verel": "Verel", "agentvision": "AgentVision"}}, "countries": {"projects": {"verel": {"US": 4875, "us": 4875, "DE": 611, "de": 611, "HK": 336, "hk": 336, "JP": 320, "jp": 320, "CN": 313, "cn": 313, "FR": 207, "fr": 207, "SG": 206, "sg": 206, "GB": 205, "gb": 205, "FI": 153, "fi": 153, "NO": 125, "no": 125, "IT": 122, "it": 122, "KR": 100, "kr": 100, "DK": 72, "dk": 72, "RU": 72, "ru": 72, "NL": 62, "nl": 62, "IE": 53, "ie": 53, "SE": 53, "se": 53, "CA": 42, "ca": 42, "IN": 32, "in": 32, "AU": 22, "au": 22, "CL": 18, "cl": 18, "MD": 17, "md": 17, "BE": 16, "be": 16, "NP": 15, "np": 15, "PL": 14, "pl": 14, "TH": 12, "th": 12, "LT": 11, "lt": 11, "TW": 5, "tw": 5, "TR": 2, "tr": 2, "ES": 2, "es": 2, "NZ": 2, "nz": 2, "IM": 2, "im": 2, "VG": 2, "vg": 2, "SA": 2, "sa": 2, "PT": 2, "pt": 2, "EE": 2, "ee": 2, "GL": 1, "gl": 1, "ZA": 1, "za": 1, "CY": 1, "cy": 1, "BR": 1, "br": 1, "TN": 1, "tn": 1, "GR": 1, "gr": 1, "AT": 1, "at": 1, "IL": 1, "il": 1, "HU": 1, "hu": 1, "KH": 1, "kh": 1, "PK": 1, "pk": 1, "LU": 1, "lu": 1, "QA": 1, "qa": 1, "ID": 1, "id": 1, "MO": 1, "mo": 1, "EG": 1, "eg": 1, "AM": 1, "am": 1, "AL": 1, "al": 1, "CZ": 1, "cz": 1, "BS": 1, "bs": 1, "VN": 1, "vn": 1, "BG": 1, "bg": 1, "MT": 1, "mt": 1, "LV": 1, "lv": 1}, "agentvision": {"US": 2257, "us": 2257, "DE": 622, "de": 622, "CN": 182, "cn": 182, "HK": 148, "hk": 148, "JP": 145, "jp": 145, "FR": 122, "fr": 122, "GB": 106, "gb": 106, "SG": 103, "sg": 103, "FI": 64, "fi": 64, "NO": 52, "no": 52, "KR": 46, "kr": 46, "DK": 36, "dk": 36, "RU": 33, "ru": 33, "NL": 32, "nl": 32, "IE": 28, "ie": 28, "CA": 25, "ca": 25, "SE": 21, "se": 21, "AU": 12, "au": 12, "CL": 11, "cl": 11, "BE": 10, "be": 10, "IN": 10, "in": 10, "TW": 6, "tw": 6, "LT": 3, "lt": 3, "CH": 3, "ch": 3, "MD": 2, "md": 2, "TH": 2, "th": 2, "VN": 2, "vn": 2, "RO": 2, "ro": 2, "EE": 1, "ee": 1, "NP": 1, "np": 1, "TR": 1, "tr": 1, "RS": 1, "rs": 1, "KZ": 1, "kz": 1, "CY": 1, "cy": 1, "IM": 1, "im": 1, "MO": 1, "mo": 1, "BG": 1, "bg": 1, "AT": 1, "at": 1, "LV": 1, "lv": 1, "IQ": 1, "iq": 1}}, "labels": {"verel": "Verel", "agentvision": "AgentVision"}}};</script>
<script>
(function(){
  var D=window.ADOPT; var col={verel:'#8b7cff',agentvision:'#5ad1e6'};
  if(D.trend && window.Chart){
    var T=D.trend, ds=Object.keys(T.datasets).map(function(p){return {label:T.labelmap[p]||p,data:T.datasets[p],
      borderColor:col[p]||'#8b7cff',backgroundColor:(col[p]||'#8b7cff')+'22',fill:true,tension:.3,pointRadius:2,borderWidth:2};});
    var c=document.createElement('canvas'); document.getElementById('aTrend').appendChild(c);
    new Chart(c,{type:'line',data:{labels:T.labels,datasets:ds},options:{responsive:true,maintainAspectRatio:false,animation:false,
      interaction:{mode:'index',intersect:false},plugins:{legend:{labels:{color:'#cfc8ff',usePointStyle:true}}},
      scales:{x:{ticks:{color:'#8a8aa6'},grid:{color:'#1b1b28'}},y:{beginAtZero:true,ticks:{color:'#8a8aa6'},grid:{color:'#1b1b28'}}}}});
  }
  if(D.countries && window.jsVectorMap){
    var C=D.countries, cur=Object.keys(C.projects)[0], map=null;
    function vals(p){return C.projects[p]||{};}
    function build(p){cur=p; var h=document.getElementById('aMap'); if(map){try{map.destroy();}catch(e){}} h.innerHTML='';
      map=new jsVectorMap({selector:'#aMap',map:'world',zoomButtons:true,backgroundColor:'transparent',
        regionStyle:{initial:{fill:'#1c1c2b',stroke:'#0a0a11',strokeWidth:0.4},hover:{fill:'#5ad1e6'}},
        series:{regions:[{attribute:'fill',scale:['#241f45','#6a5acd','#8b7cff','#5ad1e6'],normalizeFunction:'polynomial',values:vals(p)}]},
        onRegionTooltipShow:function(e,tt,code){var v=vals(cur)[code]||vals(cur)[code&&code.toUpperCase()]||0;
          tt.text('<b>'+tt.text()+'</b><br>'+v.toLocaleString()+' downloads',true);}});
      document.querySelectorAll('.adopt .tab').forEach(function(b){b.classList.toggle('on',b.dataset.p===cur);});}
    document.querySelectorAll('.adopt .tab').forEach(function(b){b.addEventListener('click',function(){build(b.dataset.p);});});
    build(cur);
  }
})();
</script>

