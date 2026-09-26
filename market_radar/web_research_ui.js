/* Isolated optional panel. No inline handlers or dynamically executed HTML. */
(() => {
  "use strict";
  const host = document.getElementById("view-research");
  if (!host) return;
  const style = document.createElement("style");
  style.textContent = `
  .wr-panel{margin:0 0 22px;background:#fff;border:1px solid #cdd7ef;border-top:5px solid #4c52b8;border-radius:14px;padding:16px;color:#17253c}
  .wr-head{display:flex;gap:12px;justify-content:space-between;align-items:flex-start}.wr-head h2{margin:0;font-size:19px}.wr-muted{color:#5d6d85;font-size:12px;line-height:1.7}
  .wr-badge{display:inline-block;padding:5px 9px;border-radius:8px;font-size:12px;background:#edf1fb;color:#3f4d92}.wr-warning{background:#fff2d6;color:#875900}.wr-success{background:#e4f4ed;color:#176e52}
  .wr-steps{display:flex;gap:7px;flex-wrap:wrap;margin:12px 0}.wr-steps span{padding:6px 10px;background:#edf3fd;border-radius:8px;font-size:12px}.wr-steps span:nth-child(2){background:#e4f4ef}.wr-steps span:nth-child(3){background:#fff1dd}.wr-steps span:nth-child(4){background:#eeeaff}
  .wr-candidates{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.wr-candidates button,.wr-refresh{padding:7px 10px;border:1px solid #bdcbee;background:#f3f6fe;border-radius:8px;cursor:pointer;color:#293e72}.wr-candidates button:disabled{opacity:.5;cursor:not-allowed}
  .wr-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.wr-card{border:1px solid #d7e0ed;border-left:4px solid #5361bf;border-radius:10px;padding:12px;min-width:0}.wr-card h3{margin:0 0 7px;font-size:15px}.wr-report{white-space:pre-wrap;font-size:13px;line-height:1.85;overflow-wrap:anywhere;margin-top:10px}.wr-report a,.wr-sources a{color:#254fa1;text-decoration:underline}.wr-sources{margin:10px 0 0;padding:0;list-style:none;overflow-wrap:anywhere}.wr-sources li{margin:5px 0;font-size:12px}.wr-card details{margin-top:9px}.wr-card summary{cursor:pointer;color:#304d85}.wr-error{color:#983b36;background:#fff0ee;border-radius:8px;padding:9px}.wr-settings{margin:10px 0;border:1px solid #e0e5f0;border-radius:8px;padding:8px 10px}
  @media(max-width:850px){.wr-grid{grid-template-columns:1fr}.wr-panel{padding:12px}.wr-head{flex-wrap:wrap}}
  `;
  document.head.append(style);
  const el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined && text !== null) n.textContent = String(text);
    if (cls) n.className = cls;
    return n;
  };
  const panel = el("section", null, "wr-panel");
  panel.id = "web-research-panel";
  const header = el("div", null, "wr-head");
  const heading = el("div");
  heading.append(el("h2", "외부 웹 조사 · AI 종합"), el("div", "기존 로컬 규칙 요약과 별도입니다. 인용 있는 AI 보고서도 검토가 필요합니다.", "wr-muted"));
  const refresh = el("button", "상태 새로고침", "wr-refresh");
  header.append(heading, refresh);
  const steps = el("div", null, "wr-steps");
  ["1 웹 검색", "2 출처·종목 대조", "3 반복·반대 근거", "4 종합과 인용"].forEach(t => steps.append(el("span", t)));
  const state = el("div", "설정 확인 중…", "wr-badge");
  const note = el("div", null, "wr-muted");
  const candidateBox = el("div", null, "wr-candidates");
  const cards = el("div", null, "wr-grid");
  const settings = el("details", null, "wr-settings");
  settings.append(el("summary", "비용·개인정보·설정"), el("p", "기본값은 외부 AI 꺼짐입니다. OPENAI_API_KEY, WEB_RESEARCH_MODEL, WEB_RESEARCH_ENABLED=1을 Mac의 .env에 직접 설정해야 실행됩니다. 키를 이 화면이나 채팅에 입력하지 마세요. 별도 API 요금이 발생합니다. 자동실행은 WEB_RESEARCH_AUTO=1인 경우에만 동작합니다.", "wr-muted"), el("p", "외부 전송: 종목명·코드·관측 시각·순위·공개 뉴스 제목/URL. Telegram 원문·비공개 채널명·계좌·비밀번호는 전송하지 않습니다. 호출 횟수 제한은 요금 총액의 보장이 아닙니다.", "wr-muted"));
  panel.append(header, steps, state, note, candidateBox, cards, settings);
  host.prepend(panel);
  let busy = false;
  let lastSignature = "";
  let latest = null;
  const names = {
    DISABLED:"외부 AI 꺼짐 · 추가 호출 없음", WAITING_FOR_KEY:"API 키 설정 대기", WAITING_FOR_MODEL:"모델 설정 대기",
    READY:"외부 AI 사용 가능", IDLE:"대기", QUEUED:"조사 대기열", RUNNING:"웹 조사 중", CITED_REPORT:"인용 포함 · AI 보고서",
    EVIDENCE_INCOMPLETE:"출처 미충족 · 검토 필요", ERROR:"조사 실패", UNCERTAIN:"완료 여부 미확인 · 자동 재호출 안 함",
    EXPIRED:"대기 시간 초과", BUDGET_PAUSED:"호출 한도 도달 · 일시중지", AUTO_REQUIRES_RECENT_PRICE_BAR:"자동조사: 최근 가격 자료 대기"
  };
  const stamp = value => value ? new Date(value).toLocaleString("ko-KR", {timeZone:"Asia/Seoul"}) : "미확인";
  function accessKey() {
    try { return localStorage.getItem("marketRadarToken") || ""; } catch (_) { return ""; }
  }
  function link(url, title) {
    try {
      const u = new URL(url);
      if (!["https:","http:"].includes(u.protocol) || u.username || u.password) return el("span", title);
      const a = el("a", title);
      a.href = u.href; a.target = "_blank"; a.rel = "noopener noreferrer";
      return a;
    } catch (_) { return el("span", title); }
  }
  function annotated(report) {
    const box = el("div", null, "wr-report");
    const chars = Array.from(report.text || ""); // API offsets count Unicode characters, not JS UTF-16 units.
    const annotations = [...(report.citations || [])].sort((a,b) => a.start - b.start);
    let pos = 0, count = 0;
    for (const a of annotations) {
      if (!Number.isInteger(a.start) || !Number.isInteger(a.end) || a.start < pos || a.end > chars.length || a.end <= a.start) continue;
      box.append(document.createTextNode(chars.slice(pos,a.start).join("")));
      box.append(link(a.url, "[출처 " + (++count) + "]"));
      pos = a.end;
    }
    box.append(document.createTextNode(chars.slice(pos).join("")));
    return box;
  }
  async function request(job, button) {
    if (!window.confirm(job.stock_name + "의 공개 자료를 외부 AI로 조사합니다. 별도 API 요금이 발생합니다. 실행할까요?")) return;
    button.disabled = true;
    try {
      const r = await fetch("/api/web-research", {method:"POST", headers:{"Content-Type":"application/json","x-dashboard-token":accessKey()}, body:JSON.stringify({job_id:job.id})});
      if (!r.ok) throw new Error("요청 실패 HTTP " + r.status);
      await load(true);
    } catch(e) { note.textContent = e.message; } finally { button.disabled = latest?.config?.gate !== "READY"; }
  }
  function render(data) {
    latest = data;
    const cfg = data.config || {}, use = data.usage || {}, worker = data.worker || {};
    state.textContent = names[cfg.gate] || cfg.gate || "설정 미확인";
    state.className = "wr-badge " + (cfg.gate === "READY" ? "wr-success" : "wr-warning");
    const workerAge = worker.updated_at ? (Date.now()-Date.parse(worker.updated_at))/1000 : Infinity;
    note.textContent = `오늘 ${use.daily ?? 0}/${cfg.daily_limit ?? "-"}회 · 최근 1시간 ${use.hourly ?? 0}/${cfg.hourly_limit ?? "-"}회 · ${cfg.automatic ? "자동+수동" : "수동"} · 작업기 ${workerAge > 240 ? "응답 지연/미시작" : (names[worker.status] || worker.status || "대기")}`;
    const signature = JSON.stringify([cfg.gate, data.candidates, data.runs]);
    if (signature === lastSignature) return;
    lastSignature = signature;
    const open = new Set([...cards.querySelectorAll("details[open]")].map(d => d.dataset.run));
    candidateBox.replaceChildren(); cards.replaceChildren();
    for (const job of data.candidates || []) {
      const button = el("button", job.stock_name + " 조사");
      button.disabled = cfg.gate !== "READY";
      button.addEventListener("click", () => request(job, button));
      candidateBox.append(button);
    }
    if (!(data.candidates || []).length) candidateBox.append(el("span", "최근 24시간 로컬 리서치 큐에 후보가 없습니다.", "wr-muted"));
    if (!(data.runs || []).length) cards.append(el("p", "아직 외부 AI 조사를 실행하지 않았습니다. 로컬 분석을 외부 조사 완료로 표시하지 않습니다.", "wr-muted"));
    for (const run of data.runs || []) {
      const card = el("article", null, "wr-card");
      card.append(el("h3", run.stock_name + " · " + run.stock_code), el("span", names[run.status] || run.status, "wr-badge " + (run.status === "CITED_REPORT" ? "wr-success" : "wr-warning")), el("div", "요청 " + stamp(run.created_at) + " · 완료 " + stamp(run.completed_at), "wr-muted"));
      if (run.error_code) card.append(el("p", run.error_code, "wr-error"));
      if (run.report) {
        const r = run.report, details = el("details");
        details.dataset.run = String(run.id); details.open = open.has(String(run.id));
        details.append(el("summary", "종합 분석과 근거 펼치기"), annotated(r));
        const sources = el("ul", null, "wr-sources");
        for (const s of r.sources || []) { const li = el("li"); li.append(link(s.url, s.title || s.url)); sources.append(li); }
        details.append(sources, el("p", r.notice, "wr-muted"));
        card.append(el("div", `검색 도구 ${r.web_tool_calls ?? 0}회 · 인용 ${(r.citations || []).length}개 · 모델 ${run.model || "미확인"}`, "wr-muted"), details);
      }
      cards.append(card);
    }
  }
  async function load(force = false) {
    if (busy || (!force && !host.classList.contains("active"))) return;
    const key = accessKey();
    if (!key) { state.textContent = "대시보드 접속키 필요"; return; }
    busy = true;
    const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 12000);
    try {
      const r = await fetch("/api/web-research", {headers:{"x-dashboard-token":key}, signal:ctl.signal, cache:"no-store"});
      if (!r.ok) throw new Error("외부 조사 모듈 HTTP " + r.status);
      render(await r.json());
    } catch(e) { state.textContent = e.name === "AbortError" ? "상태 응답 시간 초과" : e.message; state.className = "wr-badge wr-warning"; }
    finally { clearTimeout(timer); busy = false; }
  }
  refresh.addEventListener("click", () => load(true));
  document.querySelectorAll('[data-view="research"]').forEach(b => b.addEventListener("click", () => load(true)));
  load(true);
  setInterval(() => load(false), 15000);
})();
