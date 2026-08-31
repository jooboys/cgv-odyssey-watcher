#!/usr/bin/env python3
"""텔레그램 봇 토큰을 넣으면 '내 챗 ID'를 찾아준다.

사용법:  python get_chat_id.py <봇토큰>
미리 텔레그램에서 내 봇에게 아무 메시지나 한 번 보내야 한다.
"""
import sys
import json
import urllib.request

if len(sys.argv) < 2:
    print("사용법: python get_chat_id.py <봇토큰>")
    sys.exit(1)

token = sys.argv[1].strip()
url = f"https://api.telegram.org/bot{token}/getUpdates"

try:
    with urllib.request.urlopen(url, timeout=20) as resp:
        body = json.load(resp)
except Exception as e:
    print(f"❌ 요청 실패: {e}")
    print("   봇 토큰이 정확한지 확인해 주세요.")
    sys.exit(1)

if not body.get("ok"):
    print(f"❌ 텔레그램 응답 오류: {body}")
    sys.exit(1)

chats = {}
for upd in body.get("result", []):
    msg = upd.get("message") or upd.get("channel_post") or {}
    chat = msg.get("chat")
    if chat:
        name = chat.get("title") or " ".join(
            filter(None, [chat.get("first_name"), chat.get("last_name")])
        ) or chat.get("username") or "(이름없음)"
        chats[chat["id"]] = name

if not chats:
    print("❌ 아직 받은 메시지가 없습니다.")
    print("   텔레그램에서 방금 만든 봇을 찾아 [시작]을 누르고 아무 메시지나 보낸 뒤")
    print("   이 명령을 다시 실행해 주세요.")
    sys.exit(1)

print("✅ 찾았습니다. 아래 숫자가 당신의 TELEGRAM_CHAT_ID 입니다.\n")
for cid, name in chats.items():
    print(f"   {cid}   ← {name}")
