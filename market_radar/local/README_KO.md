# Market Radar - Mac mini 로컬 서버

## 권장 역할
- Mac mini: 24시간 데이터 서버
- Windows desktop: HTS/실제 매매 + 대시보드
- Notebook: 이동형 대시보드/모니터링

## 첫 설치
1. Mac mini에 Docker Desktop과 Git 설치
2. 저장소 clone
3. market_radar/local 이동
4. 실행권한:
   chmod +x start_mac.sh telegram_login_mac.sh stop_mac.sh
5. ./start_mac.sh
6. 자동 생성된 .env에 키 입력
7. ./telegram_login_mac.sh
8. ./start_mac.sh

## 대시보드
Mac mini 자체:
http://localhost:8080

같은 와이파이/LAN의 다른 PC:
http://<Mac-mini-LAN-IP>:8080

외부 인터넷에서 접속할 때는 포트포워딩보다 Tailscale 같은 사설망을 권장.

## Kiwoom
초기 테스트:
KIWOOM_MODE=demo
APP_KEY_MOCK=...
APP_SECRET_MOCK=...

실전:
KIWOOM_MODE=real
APP_KEY=...
APP_SECRET=...

키움 사이트에는 Mac mini가 연결된 네트워크의 공인 IP를 등록해야 함.

## 보안
.env, data/*.session 파일을 GitHub에 올리지 말 것.
