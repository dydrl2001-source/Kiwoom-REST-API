# Market Radar Mobile

## 목적

Mac mini는 Kiwoom/Telegram/Postgres 수집기 역할을 유지하고, iPhone은 읽기 전용 모바일 PWA로 시장을 확인한다.
비밀키(APP_SECRET, Telegram session, OpenAI key)는 모바일 HTML에 포함하지 않는다.

## 모바일 화면

- 오늘 장 한줄
- 실시간 데이터/Telegram/최강 테마/차트 신호
- 주도 테마 카드
- 급부상 Top12: 순위변화, 거래대금, 최근 구간 대금, 재료, OS 요약, 고점/바닥
- 관찰 후보 Top5
- 전체 테마
- +4% 거래대금 강세
- 수집 상태

주소:

- 같은 Wi-Fi: `http://<Mac-LAN-IP>:8080/mobile`
- 원격 안전 접속: Tailscale Serve가 표시하는 `https://<mac>.<tailnet>.ts.net/mobile`

## 설치

Mac:

```bash
cd ~/Kiwoom-REST-API
git pull --ff-only
cd market_radar/local
docker compose up -d --no-deps --build radar-api
chmod +x mobile_url_mac.sh enable_mobile_remote_mac.sh
./mobile_url_mac.sh
```

iPhone Safari에서 같은 Wi-Fi LAN URL을 연다.
처음 한 번 DASHBOARD_TOKEN을 입력하면 기기의 localStorage에 저장한다.

Safari 공유 버튼 → **홈 화면에 추가**를 선택하면 standalone PWA처럼 실행된다.

## 집 밖에서 사용

Mac/iPhone에 Tailscale을 설치하고 같은 tailnet으로 로그인한 뒤 Mac에서:

```bash
cd ~/Kiwoom-REST-API/market_radar/local
./enable_mobile_remote_mac.sh
```

Tailscale Serve는 로컬 8080을 tailnet 내부 HTTPS로만 프록시한다.
공개 Funnel은 사용하지 않는다.

## 보안 경계

- `/api/dashboard`는 기존 DASHBOARD_TOKEN을 계속 요구한다.
- 서비스워커는 `/api/` 응답을 캐시하지 않는다.
- 모바일 페이지에는 Kiwoom/OpenAI/Telegram 비밀키가 들어가지 않는다.
- Tailscale Serve 사용 시 8080 자체를 공유기 포트포워딩으로 열지 않는다.
