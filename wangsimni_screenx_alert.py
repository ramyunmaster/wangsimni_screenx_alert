"""
CGV 왕십리 SCREENX 예매 오픈 감지 -> Discord 알림 (GitHub Actions 버전, 자동 날짜 롤링)

이 스크립트는 "1번 실행하고 끝"나는 구조야.
GitHub Actions가 5분마다 이 스크립트를 새로 실행해줘.

날짜를 직접 지정하지 않고, 실행 시점의 "오늘"부터 WINDOW_DAYS 만큼의 날짜를
매번 자동으로 계산해서 전부 체크해. 그래서 CGV가 언제 며칠치를 한꺼번에 풀든
(예: 8/1~8/5 한번에, 혹은 하루씩) 그 범위 안에만 있으면 자동으로 걸림.

"이전에 뭘 봤는지"는 seen_sessions.json 파일에 저장해두고,
다음 실행 때 그 파일을 읽어서 "새로 생긴 회차"만 판단해.

필요한 환경변수:
- DISCORD_WEBHOOK_URL : Discord 웹훅 주소 (GitHub Secrets에 저장)
- MOV_NO              : 영화 번호 (workflow yml 파일에서 직접 수정)
- WINDOW_DAYS         : 오늘부터 몇 일치를 체크할지 (기본 14일)
"""

import requests
import json
import os
import sys
import time
from datetime import datetime, timedelta

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


def generate_date_range(window_days: int) -> list:
    """오늘부터 window_days 만큼의 날짜(YYYYMMDD)를 자동 생성"""
    today = datetime.now()
    return [(today + timedelta(days=i)).strftime("%Y%m%d") for i in range(window_days)]


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


def extract_target_sessions(data: dict, scn_ymd: str) -> dict:
    sessions = {}
    for item in data.get("data", []):
        if SCREEN_KEYWORD in item.get("scnsNm", ""):
            key = f'{scn_ymd}_{item.get("scnSseq")}_{item.get("scnsrtTm")}'
            sessions[key] = item
    return sessions


def send_discord_alert(webhook_url: str, message: str):
    try:
        requests.post(webhook_url, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"[경고] Discord 전송 실패: {e}")


def format_alert_message(scn_ymd: str, item: dict) -> str:
    date_fmt = f"{scn_ymd[:4]}-{scn_ymd[4:6]}-{scn_ymd[6:]}"
    return (
        f"🎬 **왕십리 SCREENX 예매 오픈 감지!**\n"
        f"날짜: {date_fmt}\n"
        f"시간: {item.get('scnsrtTm')} ~ {item.get('scnendTm')}\n"
        f"잔여좌석: {item.get('frSeatCnt')} / {item.get('cpSeatCnt')}\n"
        f"영화: {item.get('movNm')}"
    )


def main():
    webhook_url = get_env("DISCORD_WEBHOOK_URL")
    mov_no = get_env("MOV_NO")
    window_days = int(get_env("WINDOW_DAYS", required=False, default="14"))

    target_dates = generate_date_range(window_days)
    seen = load_seen()
    new_found = False

    for scn_ymd in target_dates:
        try:
            data = fetch_schedule(mov_no, scn_ymd)
        except Exception as e:
            print(f"[에러] {scn_ymd} API 호출 실패: {e}")
            continue

        sessions = extract_target_sessions(data, scn_ymd)

        for key, item in sessions.items():
            if key not in seen:
                seen.add(key)
                new_found = True
                print(f"[알림] 새 회차 발견: {key}")
                send_discord_alert(webhook_url, format_alert_message(scn_ymd, item))

        if sessions:
            print(f"{scn_ymd}: {len(sessions)}개 회차 확인됨")

        time.sleep(0.3)  # 날짜별 요청 사이 살짝 텀 (서버 부담 줄이기)

    if new_found:
        save_seen(seen)

    # 오래된 날짜의 기록은 계속 쌓이기만 하니, 너무 커지지 않게
    # window_days 범위 밖의 오래된 키는 정리해줌
    valid_prefixes = tuple(target_dates)
    cleaned = {k for k in seen if k.split("_")[0] in valid_prefixes}
    if len(cleaned) != len(seen):
        save_seen(cleaned)


if __name__ == "__main__":
    main()
