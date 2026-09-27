from pathlib import Path
import getpass

HERE=Path(__file__).resolve().parent
ENV=HERE/".env"

def ask(label,default=""):
    suffix=f" [{default}]" if default else ""
    v=input(f"{label}{suffix}: ").strip()
    return v or default

existing={}
if ENV.exists():
    for raw in ENV.read_text(encoding="utf-8-sig").splitlines():
        line=raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k,v=line.split("=",1); existing[k.strip()]=v.strip()

print("Kiwoom Windows Feed 설정")
print("- 키 값은 화면에 다시 출력하지 않습니다.")
mode=ask("모드 (demo/real)",existing.get("KIWOOM_MODE","demo")).lower()
url=ask("Radar API URL",existing.get("RADAR_INGEST_URL","https://radar-api-production-b5e2.up.railway.app")).rstrip("/")
ingest=existing.get("KIWOOM_INGEST_TOKEN","").strip()
if ingest:
    print("KIWOOM_INGEST_TOKEN: 이미 설정됨")
else:
    ingest=getpass.getpass("KIWOOM_INGEST_TOKEN: ").strip()
if mode=="real":
    key=getpass.getpass("실전 APP_KEY: ").strip()
    secret=getpass.getpass("실전 APP_SECRET: ").strip()
    body=f"""KIWOOM_MODE=real
APP_KEY={key}
APP_SECRET={secret}
RADAR_INGEST_URL={url}
KIWOOM_INGEST_TOKEN={ingest}
KIWOOM_POLL_SECONDS=30
"""
else:
    key=getpass.getpass("모의 APP_KEY: ").strip()
    secret=getpass.getpass("모의 APP_SECRET: ").strip()
    body=f"""KIWOOM_MODE=demo
APP_KEY_MOCK={key}
APP_SECRET_MOCK={secret}
RADAR_INGEST_URL={url}
KIWOOM_INGEST_TOKEN={ingest}
KIWOOM_POLL_SECONDS=30
"""
ENV.write_text(body,encoding="utf-8")
print(f"저장 완료: {ENV}")
print("다음: start_feed.bat 실행")
