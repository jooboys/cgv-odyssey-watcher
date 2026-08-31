# CGV 신규 예매일 알림봇

**CGV 왕십리(0074)** 에서 **오디세이(30001323)** 의 새 예매 날짜가 열리는 순간을
텔레그램으로 알려줍니다. 1분 간격으로 확인합니다.

## 어떻게 감지하나요?

CGV 예매 페이지가 내부적으로 쓰는 API를 그대로 호출합니다.

```
GET https://cgv.co.kr/api/v1/booking/searchSiteScnscYmdListByMov
      ?coCd=A420&siteNo=0074&movNo=30001323
```

이 API는 "이 극장에서 이 영화를 예매할 수 있는 날짜 목록"을 돌려줍니다.

```json
{"statusCode":0,"data":[{"scnYmd":"20260901"}, ... ,{"scnYmd":"20260908"}]}
```

이 목록을 1분마다 가져와서, **직전에 없던 날짜가 생기면** 알림을 보냅니다.
새 날짜가 감지되면 그 날짜의 상영시간표(`searchSchByMov`)도 함께 조회해서
상영관·시간·잔여좌석까지 알림에 담습니다.

## 왜 브라우저(Playwright)를 쓰지 않나요?

CGV는 Cloudflare 봇 차단을 씁니다. 일반적인 요청(curl, requests, node fetch)은
헤더를 아무리 완벽하게 맞춰도 **403**이 납니다. 차단 기준이 헤더나 쿠키가 아니라
**TLS 핸드셰이크 지문(JA3)** 이기 때문입니다.

그래서 `curl_cffi` 로 크롬의 TLS 지문만 흉내내면 그대로 **200**이 나옵니다.
헤드리스 브라우저를 띄울 필요가 없어서, 실행이 가볍고 빠르고 잘 깨지지 않습니다.

> 참고: 같은 이유로 **Cloudflare Workers 배포는 불가능**합니다.
> Workers의 `fetch`는 TLS 지문을 바꿀 수 없어서 CGV에 막힙니다.

## 실행 방식

GitHub Actions에서 돕니다. GitHub 크론은 최소 5분 간격이라,
**10분마다 잡을 띄우고 각 잡이 11분 동안 1분 간격으로 확인**합니다.
잡이 서로 겹치기 때문에 스케줄이 조금 밀려도 감시가 끊기지 않습니다.

"이미 알고 있는 날짜" 목록은 Actions 캐시(`state.json`)에 보관됩니다.

## 설정값

워크플로 파일(`.github/workflows/watch.yml`)의 `env`에서 바꿀 수 있습니다.

| 값 | 설명 |
|---|---|
| `CGV_SITE_NO` | 극장 코드 (왕십리 = `0074`) |
| `CGV_MOV_NO` | 영화 코드 (오디세이 = `30001323`) |
| `CGV_LOOP_INTERVAL` | 확인 간격(초). 기본 60 |

민감한 값 2개는 저장소 Settings → Secrets에 넣습니다.

| Secret | 설명 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather 가 준 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 알림 받을 내 텔레그램 챗 ID |

## 내 컴퓨터에서 한 번 돌려보기

```bash
pip install -r requirements.txt
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python check.py
```

챗 ID를 모를 때:

```bash
python get_chat_id.py <봇토큰>
```
