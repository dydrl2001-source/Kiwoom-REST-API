# Kiwoom Windows Feed

Railway Pro의 고정 Outbound IP 없이 키움 REST API를 사용하기 위한 로컬 수집기입니다.

## 구조

```
Kiwoom REST API
      ↓
Windows PC (이 폴더)
      ↓ HTTPS + ingest token
Railway radar-api
      ↓
Postgres
      ↓
market regime engine
```

DB 비밀번호와 Railway DATABASE_URL은 Windows에 저장하지 않습니다.

## 처음 한 번

1. 키움 REST API에서 **현재 Windows PC의 공인 IP**를 허용 IP로 등록합니다.
2. 모의투자 App Key / App Secret을 발급합니다.
3. `setup_windows.bat` 실행
4. 질문에 따라 `demo`, App Key, App Secret, ingest token을 입력합니다.
5. `start_feed.bat` 실행

## 정상 로그

```
OK rank=100 trade=100 sectors=... snapshot=...
```

이 로그가 반복되면 Railway DB에 스냅샷이 들어가고 기존 regime 엔진이 자동으로 읽습니다.

## 실전 전환

`setup_windows.bat`을 다시 실행하고 mode를 `real`로 선택한 뒤 실전 App Key/Secret을 입력합니다.

## 보안

- `.env` 파일은 Git에 올리지 마세요.
- App Key / Secret을 채팅이나 메신저로 보내지 마세요.
- Windows에는 DB 비밀번호가 저장되지 않습니다.
- 서버는 `x-kiwoom-ingest-token`이 일치하는 요청만 허용합니다.

## 장애 확인

`check_feed.bat`을 실행하면 최근 30줄의 로그를 볼 수 있습니다.
