import { SQL } from "bun";

const DB = process.env.DATABASE_URL;
const POLL = Number(process.env.REGIME_POLL_SECONDS || "30");
const STALE = Number(process.env.REGIME_STALE_SECONDS || "120");
if (!DB) throw new Error("DATABASE_URL missing");

const sql = new SQL(DB);

const schema = `
CREATE TABLE IF NOT EXISTS market_rank_snapshots (
  snapshot_time TIMESTAMPTZ NOT NULL,
  stock_code TEXT NOT NULL,
  stock_name TEXT,
  rank_no INTEGER,
  rank_change INTEGER,
  change_rate DOUBLE PRECISION,
  market_cap_krw NUMERIC,
  official_sector TEXT,
  market_theme TEXT,
  PRIMARY KEY (snapshot_time, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_rank_time ON market_rank_snapshots(snapshot_time DESC);

CREATE TABLE IF NOT EXISTS market_trade_value_snapshots (
  snapshot_time TIMESTAMPTZ NOT NULL,
  stock_code TEXT NOT NULL,
  stock_name TEXT,
  rank_no INTEGER,
  trade_value_krw NUMERIC,
  change_rate DOUBLE PRECISION,
  market_cap_krw NUMERIC,
  official_sector TEXT,
  market_theme TEXT,
  PRIMARY KEY (snapshot_time, stock_code)
);
CREATE INDEX IF NOT EXISTS idx_trade_time ON market_trade_value_snapshots(snapshot_time DESC);

CREATE TABLE IF NOT EXISTS market_sector_snapshots (
  snapshot_time TIMESTAMPTZ NOT NULL,
  sector_code TEXT NOT NULL,
  sector_name TEXT NOT NULL,
  change_rate DOUBLE PRECISION,
  trade_value_krw NUMERIC,
  rising_count INTEGER,
  flat_count INTEGER,
  falling_count INTEGER,
  PRIMARY KEY (snapshot_time, sector_code)
);
CREATE INDEX IF NOT EXISTS idx_sector_time ON market_sector_snapshots(snapshot_time DESC);

CREATE TABLE IF NOT EXISTS market_index_snapshots (
  snapshot_time TIMESTAMPTZ NOT NULL,
  index_code TEXT NOT NULL,
  index_name TEXT NOT NULL,
  current_value DOUBLE PRECISION,
  change_rate DOUBLE PRECISION,
  open_value DOUBLE PRECISION,
  high_value DOUBLE PRECISION,
  low_value DOUBLE PRECISION,
  PRIMARY KEY (snapshot_time, index_code)
);
CREATE INDEX IF NOT EXISTS idx_index_time ON market_index_snapshots(snapshot_time DESC);

CREATE TABLE IF NOT EXISTS market_regime_snapshots (
  snapshot_time TIMESTAMPTZ PRIMARY KEY,
  candidate_trend_state TEXT,
  candidate_flow_state TEXT,
  candidate_sentiment_state TEXT,
  candidate_label TEXT,
  stable_label TEXT,
  confidence DOUBLE PRECISION,
  data_freshness_sec INTEGER,
  rank_turnover_5m DOUBLE PRECISION,
  top5_trade_share DOUBLE PRECISION,
  top10_trade_share DOUBLE PRECISION,
  top_sector_share DOUBLE PRECISION,
  top3_sector_share DOUBLE PRECISION,
  largecap_trade_share DOUBLE PRECISION,
  positive_rank_share DOUBLE PRECISION,
  avg_rank_change_rate DOUBLE PRECISION,
  sector_count_top20 INTEGER,
  explanation JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_regime_time ON market_regime_snapshots(snapshot_time DESC);

CREATE TABLE IF NOT EXISTS market_regime_status (
  id INTEGER PRIMARY KEY DEFAULT 1,
  updated_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL,
  last_market_data_at TIMESTAMPTZ,
  stable_label TEXT,
  candidate_label TEXT,
  candidate_count INTEGER NOT NULL DEFAULT 0,
  note TEXT,
  CHECK (id=1)
);
`;

function num(v) {
  if (v === null || v === undefined) return null;
  const x = Number(v);
  return Number.isFinite(x) ? x : null;
}
function share(a,b) {
  if (a === null || a === undefined || !b) return null;
  return Number(a)/Number(b);
}
function turnover(a,b) {
  const A = new Set(a), B = new Set(b);
  if (!A.size && !B.size) return null;
  const U = new Set([...A,...B]);
  let inter=0;
  for (const x of A) if (B.has(x)) inter++;
  return 1 - inter/U.size;
}
function iso(v) {
  if (!v) return null;
  return new Date(v).toISOString();
}
function classify(m) {
  const reasons=[];
  let completeness=0;
  const values=[m.rank_turnover_5m,m.top5_trade_share,m.top10_trade_share,m.top_sector_share,m.top3_sector_share,m.positive_rank_share,m.sector_count_top20];
  for(const v of values) if(v!==null) completeness++;
  if(m.primary_index_change_rate!==null) completeness++;

  let trend;
  if(m.primary_index_change_rate===null){
    trend="UNKNOWN"; reasons.push("지수 데이터 부족");
  } else if(m.primary_index_change_rate>=1){
    trend="RISING"; reasons.push(`주요지수 ${m.primary_index_change_rate.toFixed(2)}%`);
  } else if(m.primary_index_change_rate<=-1){
    trend="FALLING"; reasons.push(`주요지수 ${m.primary_index_change_rate.toFixed(2)}%`);
  } else {
    trend="RANGE_OR_MIXED"; reasons.push(`주요지수 ${m.primary_index_change_rate.toFixed(2)}%`);
  }

  let flow;
  if(m.largecap_trade_share!==null && m.largecap_trade_share>=0.55){
    flow="LARGE_CAP_CONCENTRATED";
    reasons.push(`거래대금 상위 대형주 비중 ${(m.largecap_trade_share*100).toFixed(1)}%`);
  } else if(
    m.top_sector_share!==null && m.top3_sector_share!==null && m.rank_turnover_5m!==null &&
    (m.top_sector_share>=0.35 || m.top3_sector_share>=0.62) &&
    m.rank_turnover_5m<=0.45
  ){
    flow="LEADER_CONCENTRATED";
    reasons.push(`1위 섹터 점유 ${(m.top_sector_share*100).toFixed(1)}%, 조회 교체율 ${(m.rank_turnover_5m*100).toFixed(1)}%`);
  } else if(
    m.top_sector_share!==null && m.top3_sector_share!==null && m.rank_turnover_5m!==null &&
    m.top_sector_share<0.25 && m.top3_sector_share<0.50 &&
    m.rank_turnover_5m>=0.55
  ){
    flow="ROTATIONAL_DISTRIBUTED";
    reasons.push(`섹터 집중 낮음 + 조회 교체율 ${(m.rank_turnover_5m*100).toFixed(1)}%`);
  } else if(m.sector_count_top20!==null && m.sector_count_top20>=7 && m.rank_turnover_5m!==null && m.rank_turnover_5m>=0.45){
    flow="BROAD_DISTRIBUTED";
    reasons.push(`Top20에 ${m.sector_count_top20}개 섹터 분산`);
  } else {
    flow="TRANSITION_OR_MIXED";
    reasons.push("집중·분산 신호 혼재");
  }

  let sentiment;
  if(m.positive_rank_share===null || m.avg_rank_change_rate===null){
    sentiment="UNKNOWN"; reasons.push("상승 폭 데이터 부족");
  } else if(m.positive_rank_share>=0.70 && m.avg_rank_change_rate>=2.0){
    sentiment="STRONG"; reasons.push(`Top20 상승 비중 ${(m.positive_rank_share*100).toFixed(1)}%`);
  } else if(m.positive_rank_share<=0.40 || m.avg_rank_change_rate<0){
    sentiment="WEAK"; reasons.push(`Top20 상승 비중 ${(m.positive_rank_share*100).toFixed(1)}%`);
  } else {
    sentiment="NORMAL"; reasons.push(`Top20 상승 비중 ${(m.positive_rank_share*100).toFixed(1)}%`);
  }

  const tmap={RISING:"상승",FALLING:"하락",RANGE_OR_MIXED:"횡보·혼합",UNKNOWN:"추세 미확인"};
  const fmap={LEADER_CONCENTRATED:"주도주 집중",ROTATIONAL_DISTRIBUTED:"수급분산·시소타기",BROAD_DISTRIBUTED:"광범위 수급분산",LARGE_CAP_CONCENTRATED:"대형주 집중",TRANSITION_OR_MIXED:"전환·혼합"};
  const smap={STRONG:"투자심리 강함",NORMAL:"투자심리 보통",WEAK:"투자심리 위축",UNKNOWN:"심리 미확인"};
  return {
    trend,flow,sentiment,
    label:`${tmap[trend]} / ${fmap[flow]} / ${smap[sentiment]}`,
    confidence:Math.min(0.95,0.25+0.10*completeness),
    reasons
  };
}

async function latestTime(table) {
  const rows = await sql.unsafe(`SELECT MAX(snapshot_time) AS t FROM ${table}`);
  return rows[0]?.t || null;
}
async function rowsAt(table,t,limit=20) {
  if(!t) return [];
  const order=(table.includes("rank")||table.includes("trade_value"))?" ORDER BY rank_no NULLS LAST":"";
  return await sql.unsafe(`SELECT * FROM ${table} WHERE snapshot_time=$1${order} LIMIT ${Number(limit)}`,[t]);
}
async function priorRankTime(t) {
  if(!t) return null;
  const target=new Date(new Date(t).getTime()-5*60*1000);
  const rows=await sql`
    SELECT snapshot_time FROM market_rank_snapshots
    WHERE snapshot_time <= ${target}
    GROUP BY snapshot_time ORDER BY snapshot_time DESC LIMIT 1
  `;
  return rows[0]?.snapshot_time || null;
}
async function stabilize(candidate) {
  const rows=await sql`SELECT stable_label,candidate_label,candidate_count FROM market_regime_status WHERE id=1`;
  const prev=rows[0] || {};
  let count = prev.candidate_label===candidate ? Number(prev.candidate_count||0)+1 : 1;
  let stable = prev.stable_label || null;
  if(!stable || count>=3) stable=candidate;
  return {stable,count};
}
async function compute() {
  const rt=await latestTime("market_rank_snapshots");
  const tt=await latestTime("market_trade_value_snapshots");
  const st=await latestTime("market_sector_snapshots");
  const it=await latestTime("market_index_snapshots");
  const times=[rt,tt,st,it].filter(Boolean).map(x=>new Date(x));
  if(!times.length){
    await sql`
      INSERT INTO market_regime_status(id,updated_at,status,last_market_data_at,stable_label,candidate_label,candidate_count,note)
      VALUES(1,now(),'WAITING_FOR_MARKET_DATA',NULL,NULL,NULL,0,'키움 시장 데이터 대기 중')
      ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,last_market_data_at=NULL,note=excluded.note
    `;
    return;
  }
  const latest=new Date(Math.max(...times.map(x=>x.getTime())));
  const freshness=Math.max(0,Math.round((Date.now()-latest.getTime())/1000));
  const status=freshness>STALE?"STALE":"OK";

  const ranks=await rowsAt("market_rank_snapshots",rt,20);
  const trades=await rowsAt("market_trade_value_snapshots",tt,20);
  const sectors=await rowsAt("market_sector_snapshots",st,100);
  const indexes=await rowsAt("market_index_snapshots",it,10);
  const pt=await priorRankTime(rt);
  const prior=await rowsAt("market_rank_snapshots",pt,20);

  const rankTurn=pt?turnover(ranks.map(r=>r.stock_code),prior.map(r=>r.stock_code)):null;
  const vals=trades.map(r=>num(r.trade_value_krw)||0);
  const total20=vals.reduce((a,b)=>a+b,0);
  const top5=share(vals.slice(0,5).reduce((a,b)=>a+b,0),total20);
  const top10=share(vals.slice(0,10).reduce((a,b)=>a+b,0),total20);

  let largeVal=0;
  for(const r of trades){
    const cap=num(r.market_cap_krw), v=num(r.trade_value_krw)||0;
    if(cap!==null && cap>=10_000_000_000_000) largeVal+=v;
  }
  const large=share(largeVal,total20);

  const sv=sectors.map(r=>[r.sector_name,num(r.trade_value_krw)||0]).filter(x=>x[0]&&x[1]>0).sort((a,b)=>b[1]-a[1]);
  const stotal=sv.reduce((a,x)=>a+x[1],0);
  const topSector=sv.length?share(sv[0][1],stotal):null;
  const top3Sector=sv.length?share(sv.slice(0,3).reduce((a,x)=>a+x[1],0),stotal):null;
  const sectorSet=new Set(ranks.map(r=>r.official_sector).filter(Boolean));
  const sectorCount=ranks.length?sectorSet.size:null;

  const changes=ranks.map(r=>num(r.change_rate)).filter(v=>v!==null);
  const posShare=changes.length?changes.filter(x=>x>0).length/changes.length:null;
  const avgChg=changes.length?changes.reduce((a,b)=>a+b,0)/changes.length:null;

  let primary=null;
  for(const r of indexes){
    const name=String(r.index_name||"").toUpperCase(), code=String(r.index_code||"").toUpperCase();
    if(name.includes("KOSPI")||code==="001"||code==="KOSPI"){primary=r;break;}
  }
  if(!primary && indexes.length) primary=indexes[0];
  const indexChg=primary?num(primary.change_rate):null;

  const m={
    rank_turnover_5m:rankTurn,top5_trade_share:top5,top10_trade_share:top10,
    top_sector_share:topSector,top3_sector_share:top3Sector,largecap_trade_share:large,
    positive_rank_share:posShare,avg_rank_change_rate:avgChg,sector_count_top20:sectorCount,
    primary_index_change_rate:indexChg
  };
  const c=classify(m);
  const h=await stabilize(c.label);
  const explanation={
    reasons:c.reasons,
    provisional_rules:true,
    self_feedback:"초기 고정 임계값. 10거래일 이상 축적 후 시간대별 rolling percentile 방식으로 교체 예정",
    hysteresis:"동일 후보 상태 3회 연속 확인 후 안정 상태 전환",
    top_sectors:sv.slice(0,5).map(x=>({sector:x[0],trade_value_krw:x[1]})),
    data_times:{rank:iso(rt),trade:iso(tt),sector:iso(st),index:iso(it)}
  };
  const snap=new Date(Math.floor(Date.now()/1000)*1000);

  await sql`
    INSERT INTO market_regime_snapshots(
      snapshot_time,candidate_trend_state,candidate_flow_state,candidate_sentiment_state,
      candidate_label,stable_label,confidence,data_freshness_sec,rank_turnover_5m,
      top5_trade_share,top10_trade_share,top_sector_share,top3_sector_share,
      largecap_trade_share,positive_rank_share,avg_rank_change_rate,sector_count_top20,explanation
    ) VALUES(
      ${snap},${c.trend},${c.flow},${c.sentiment},${c.label},${h.stable},${c.confidence},${freshness},
      ${rankTurn},${top5},${top10},${topSector},${top3Sector},${large},${posShare},${avgChg},${sectorCount},
      ${JSON.stringify(explanation)}
    ) ON CONFLICT(snapshot_time) DO NOTHING
  `;
  await sql`
    INSERT INTO market_regime_status(id,updated_at,status,last_market_data_at,stable_label,candidate_label,candidate_count,note)
    VALUES(1,now(),${status},${latest},${h.stable},${c.label},${h.count},${status==="OK"?"시장 데이터 정상":`시장 데이터 ${freshness}초 지연`})
    ON CONFLICT(id) DO UPDATE SET
      updated_at=excluded.updated_at,status=excluded.status,last_market_data_at=excluded.last_market_data_at,
      stable_label=excluded.stable_label,candidate_label=excluded.candidate_label,candidate_count=excluded.candidate_count,note=excluded.note
  `;
}

await sql.unsafe(schema);
console.log("market-regime engine ready");
while(true){
  try{ await compute(); }
  catch(e){
    console.error("regime error", String(e?.message||e).slice(0,500));
    try{
      await sql`
        INSERT INTO market_regime_status(id,updated_at,status,note)
        VALUES(1,now(),'ERROR',${String(e?.message||e).slice(0,500)})
        ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,status=excluded.status,note=excluded.note
      `;
    }catch{}
  }
  await Bun.sleep(POLL*1000);
}
