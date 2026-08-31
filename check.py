#!/usr/bin/env python3
"""CGV 신규 예매일 감시 -> 텔레그램 알림.

CGV는 Cloudflare 봇 차단을 쓰기 때문에 일반 HTTP 클라이언트(requests/curl)는 403이 난다.
curl_cffi 로 크롬의 TLS 지문을 흉내내면 통과한다. (헤드리스 브라우저 불필요)
"""
import json
import os
import sys
import time
from datetime import datetime, date, timezone, timedelta

from curl_cffi import requests

KST = timezone(timedelta(hours=9))
WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]

BASE = "https://cgv.co.kr/api/v1/booking"
CO_CD = "A420"

SITE_NO = os.environ.get("CGV_SITE_NO", "0074")
SITE_NAME = os.environ.get("CGV_SITE_NAME", "CGV 왕십리")
MOV_NO = os.environ.get("CGV_MOV_NO", "30001323")
MOV_NAME = os.environ.get("CGV_MOV_NAME", "오디세이")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

STATE_FILE = os.environ.get(
    "CGV_STATE_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json"),
)

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://cgv.co.kr/cnm/movieBook/movie",
    "Origin": "https://cgv.co.kr",
}

BOOKING_URL = "https://cgv.co.kr/cnm/movieBook/movie"
MOVIE_URL = f"https://cgv.co.kr/cnm/cgvChart/movieChart/{MOV_NO}"


def log(msg):
    print(f"[{datetime.now(KST):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def api_get(session, path, params, tries=3):
    """CGV API 호출. 일시적 실패는 재시도."""
    last = None
    for attempt in range(tries):
        try:
            r = session.get(f"{BASE}/{path}", params=params, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                body = r.json()
                if body.get("statusCode") == 0:
                    return body.get("data") or []
                last = f"statusCode={body.get('statusCode')} {body.get('statusMessage')}"
            else:
                last = f"HTTP {r.status_code}"
        except Exception as e:  # 네트워크/파싱 오류
            last = f"{type(e).__name__}: {e}"
        if attempt < tries - 1:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{path} 실패: {last}")


def fetch_open_dates(session):
    """이 극장에서 이 영화의 '예매 가능한 날짜' 목록 (YYYYMMDD)."""
    data = api_get(session, "searchSiteScnscYmdListByMov",
                   {"coCd": CO_CD, "siteNo": SITE_NO, "movNo": MOV_NO})
    return sorted({row["scnYmd"] for row in data if row.get("scnYmd")})


def fetch_showtimes(session, ymd):
    """특정 날짜의 상영 회차 목록."""
    try:
        return api_get(session, "searchSchByMov",
                       {"coCd": CO_CD, "siteNo": SITE_NO, "scnYmd": ymd,
                        "movNo": MOV_NO, "rtctlScopCd": "08"}, tries=2)
    except Exception as e:
        log(f"  상영시간표 조회 실패({ymd}): {e}")
        return []


def fmt_date(ymd):
    d = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
    return f"{d:%Y-%m-%d} ({WEEKDAY_KR[d.weekday()]})"


def fmt_time(hhmm):
    return f"{hhmm[:2]}:{hhmm[2:]}" if hhmm and len(hhmm) == 4 else (hhmm or "")


def fmt_showtimes(rows):
    """상영관별로 묶어서 사람이 읽을 수 있게."""
    if not rows:
        return "  (상영시간표는 아직 조회되지 않음 — 앱에서 확인)"
    by_screen = {}
    for r in rows:
        key = r.get("expoScnsNm") or r.get("scnsNm") or "상영관"
        by_screen.setdefault(key, []).append(r)
    lines = []
    for screen, items in by_screen.items():
        items.sort(key=lambda r: r.get("scnsrtTm") or "")
        kind = items[0].get("movkndDsplNm") or ""
        head = f"  🎞 {screen}" + (f" · {kind}" if kind and kind not in screen else "")
        lines.append(head)
        for r in items:
            start = fmt_time(r.get("scnsrtTm"))
            free = r.get("frSeatCnt")
            total = r.get("cpSeatCnt") or r.get("stcnt")
            seat = f" — 잔여 {free}/{total}석" if free is not None and total else ""
            lines.append(f"     {start}{seat}")
    return "\n".join(lines)


def send_telegram(text, silent=False):
    if not BOT_TOKEN or not CHAT_ID:
        log("텔레그램 토큰/챗ID가 없어 전송 생략. 메시지 내용:\n" + text)
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
        "disable_notification": silent,
    }
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=20)
            if r.status_code == 200:
                return True
            log(f"텔레그램 전송 실패 HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            log(f"텔레그램 전송 오류: {type(e).__name__}: {e}")
        time.sleep(2 * (attempt + 1))
    return False


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        log(f"상태파일 손상({e}) — 새로 시작")
        return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def run_once(session):
    state = load_state()
    known = set(state.get("known_dates", []))
    fails = state.get("consecutive_failures", 0)

    try:
        dates = fetch_open_dates(session)
    except Exception as e:
        fails += 1
        log(f"조회 실패({fails}회 연속): {e}")
        # 10회(약 10분) 연속 실패하면 한 번만 경고. 조용히 죽는 것을 막는다.
        if fails == 10 and not state.get("failure_alerted"):
            send_telegram(
                f"⚠️ CGV 감시 오류\n{MOV_NAME} / {SITE_NAME} 조회가 10회 연속 실패했습니다.\n"
                f"사유: {e}\n\nCGV가 차단 방식을 바꿨을 수 있습니다."
            )
            state["failure_alerted"] = True
        state["consecutive_failures"] = fails
        save_state(state)
        return 1

    if fails >= 10 and state.get("failure_alerted"):
        send_telegram(f"✅ CGV 감시 정상 복구 ({MOV_NAME} / {SITE_NAME})", silent=True)
    state["consecutive_failures"] = 0
    state["failure_alerted"] = False
    state["last_checked"] = datetime.now(KST).isoformat(timespec="seconds")

    # 첫 실행: 지금 열려 있는 날짜를 기준선으로 저장만 하고 알리지 않는다.
    if "known_dates" not in state:
        state["known_dates"] = dates
        save_state(state)
        log(f"기준선 저장: {len(dates)}일 ({dates[0] if dates else '-'} ~ {dates[-1] if dates else '-'})")
        send_telegram(
            f"👀 감시 시작\n{MOV_NAME} · {SITE_NAME}\n\n"
            f"현재 열린 예매일: {len(dates)}일\n"
            f"{fmt_date(dates[0]) if dates else '-'} ~ {fmt_date(dates[-1]) if dates else '-'}\n\n"
            f"새 날짜가 열리면 바로 알려드릴게요.",
            silent=True,
        )
        return 0

    new_dates = [d for d in dates if d not in known]

    if new_dates:
        log(f"🔔 신규 예매일 {len(new_dates)}개: {', '.join(new_dates)}")
        blocks = []
        for ymd in new_dates:
            blocks.append(f"📅 {fmt_date(ymd)}\n{fmt_showtimes(fetch_showtimes(session, ymd))}")
        msg = (
            f"🎬 {MOV_NAME} · {SITE_NAME}\n"
            f"🔔 새 예매일이 열렸습니다! ({len(new_dates)}일)\n\n"
            + "\n\n".join(blocks)
            + f"\n\n▶ 예매: {BOOKING_URL}\n▶ 영화정보: {MOVIE_URL}"
        )
        if not send_telegram(msg):
            # 전송 실패 시 상태를 갱신하지 않아 다음 회차에 재시도된다.
            log("전송 실패 — 상태 미갱신, 다음 회차에 재시도")
            return 1
    else:
        log(f"변화 없음 ({len(dates)}일, 마지막 {dates[-1] if dates else '-'})")

    state["known_dates"] = dates
    save_state(state)
    return 0


def main():
    session = requests.Session(impersonate="chrome")

    interval = int(os.environ.get("CGV_LOOP_INTERVAL", "0"))
    duration_min = float(os.environ.get("CGV_LOOP_DURATION_MIN", "0"))

    # 단발 실행 모드
    if interval <= 0:
        return run_once(session)

    # 루프 모드: GitHub Actions 처럼 1분 크론이 없는 환경에서 잡 안에서 반복한다.
    deadline = time.monotonic() + duration_min * 60
    log(f"루프 시작 — {interval}초 간격, 약 {duration_min:g}분 동안")
    n = 0
    while True:
        started = time.monotonic()
        n += 1
        try:
            run_once(session)
        except Exception as e:  # 루프 자체는 절대 죽지 않게
            log(f"예상치 못한 오류: {type(e).__name__}: {e}")
        if time.monotonic() + interval > deadline:
            log(f"루프 종료 — 총 {n}회 확인")
            return 0
        time.sleep(max(0, interval - (time.monotonic() - started)))


if __name__ == "__main__":
    sys.exit(main())
