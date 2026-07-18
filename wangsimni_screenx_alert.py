"""
CGV 왕십리 SCREENX 예매 오픈 감지 -> Discord 알림 (GitHub Actions 버전)

이 스크립트는 "1번 실행하고 끝"나는 구조야.
GitHub Actions가 5분마다 이 스크립트를 새로 실행해줘.

"이전에 뭘 봤는지"는 seen_sessions.json 파일에 저장해두고,
다음 실행 때 그 파일을 읽어서 "새로 생긴 회차"만 판단해.
(이 파일은 GitHub Actions가 자동으로 커밋해서 저장소에 저장해줌)

필요한 환경변수:
- DISCORD_WEBHOOK_URL : Discord 웹훅 주소 (GitHub Secrets에 저장)
- MOV_NO              : 영화 번호 (workflow yml 파일에서 직접 수정)
- TARGET_DATE          : 확인할 날짜 YYYYMMDD (workflow yml 파일에서 직접 수정)
"""

import requests
import json
import os
import sys

CO_CD = "A420"
SITE_NO = "0074"  # 왕십리
SCREEN_KEYWORD = "SCREENX"
STATE_FILE = "seen_sessions.json"
API_URL = "https://cgv.co.kr/api/v1/booking/searchSchByMov"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://cgv.co.kr/cnm/movieBook/movie",
}


def get_env(name: str, required: bool = True, default: str = None) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        print(f"[에러] 환경변수 {name} 이(가) 설정되지 않았어.")
        sys.exit(1)
    return value


def load_seen() -> set:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                return set()
    return set()


def save_seen(seen: set):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def fetch_schedule(mov_no: str, scn_ymd: str) -> dict:
    params = {
        "coCd": CO_CD,
        "siteNo": SITE_NO,
        "scnYmd": scn_ymd,
        "movNo": mov_no,
        "rtctlScopCd": "08",
    }
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.json()


def extract_target_sessions(data: dict) -> dict:
    sessions = {}
    for item in data.get("data", []):
        if SCREEN_KEYWORD in item.get("scnsNm", ""):
            key = f'{item.get("scnSseq")}_{item.get("scnsrtTm")}'
            sessions[key] = item
    return sessions


def send_discord_alert(webhook_url: str, message: str):
    try:
        requests.post(webhook_url, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"[경고] Discord 전송 실패: {e}")


def format_alert_message(item: dict) -> str:
    return (
        f"🎬 **왕십리 SCREENX 예매 오픈 감지!**\n"
        f"시간: {item.get('scnsrtTm')} ~ {item.get('scnendTm')}\n"
        f"잔여좌석: {item.get('frSeatCnt')} / {item.get('cpSeatCnt')}\n"
        f"영화: {item.get('movNm')}"
    )


def main():
    webhook_url = get_env("DISCORD_WEBHOOK_URL")
    mov_no = get_env("MOV_NO")
    target_date = get_env("TARGET_DATE")

    seen = load_seen()

    try:
        data = fetch_schedule(mov_no, target_date)
    except Exception as e:
        print(f"[에러] API 호출 실패: {e}")
        # API 호출 실패는 워크플로우 자체를 실패시키지 않고 조용히 넘어감 (일시적 오류일 수 있음)
        sys.exit(0)

    sessions = extract_target_sessions(data)
    new_found = False

    for key, item in sessions.items():
        if key not in seen:
            seen.add(key)
            new_found = True
            print(f"[알림] 새 회차 발견: {key}")
            send_discord_alert(webhook_url, format_alert_message(item))

    if not sessions:
        print("아직 스케줄 없음")
    elif not new_found:
        print("변경 없음 (이미 알림 보낸 회차들뿐)")

    if new_found:
        save_seen(seen)


if __name__ == "__main__":
    main()
