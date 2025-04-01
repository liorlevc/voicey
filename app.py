import os
import json
import base64
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from dotenv import load_dotenv
import uvicorn

load_dotenv()
# Configuration
OPENAI_API_KEY = os.getenv(
    'OPENAI_API_KEY')  # requires OpenAI Realtime API Access

SYSTEM_MESSAGE = (
" שמך רעות ואת נציגת שירות של אפליקציית 'תוביל אותי', שמתמחה במציאת חברות הובלה ללקוחות. את דוברת עברית ויודעת להציע תמיכה מועילה ונעימה. התשובות שלך צריכות להיות ישירות, חמות וקלות להבנה, ולא להגזים במילים. חשוב להיות קשובה לצרכים של הלקוח ולהגיב בנימה נלהבת אך טבעית, כאילו מדובר בשיחה עם אדם אמיתי ולא עם מערכת אוטומטית. התשובות שלך צריכות להיות פשוטות, ענייניות, עם חיוך ותחושת קבלה, לא יותר מדי פורמליות. תמיד תהיי זמינה לשאלות, ותשני את הטון שלך לפי הצורך של הלקוח – אם הוא צריך עזרה או טיפים למעבר דירה, אם הוא רק רוצה לברר משהו, או אם הוא צריך עזרה בשימוש באפליקציה.")
VOICE = 'shimmer'
LOG_EVENT_TYPES = [
    'response.content.done', 'rate_limits.updated', 'response.done',
    'input_audio_buffer.committed', 'input_audio_buffer.speech_stopped',
    'input_audio_buffer.speech_started', 'session.created'
]
app = FastAPI()
if not OPENAI_API_KEY:
    raise ValueError(
        'Missing the OpenAI API key. Please set it in the .env file.')


@app.api_route("/", methods=["GET", "POST"])
async def index_page():
    return "<h1>Server is up and running.Youtube: @the_ai_solopreneur </h1>"


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call and return TwiML response to connect to Media Stream."""
    response = VoiceResponse()
    # Use language attribute to specify Hebrew
    response.say(
        "אתה מחובר לשיחה", 
        language="he-IL", 
        voice="Polly.Ruth"
    )
    response.pause(length=1)
    response.say("שיחה נעימה", language="he-IL", voice="Polly.Ruth")
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connections between Twilio and OpenAI."""
    print("Client connected")
    await websocket.accept()

    # Fix for the headers issue
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1"
    }
    
    async with websockets.connect(
            'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01',
            extra_headers=headers) as openai_ws:
        await send_session_update(openai_ws)
        stream_sid = None

        async def receive_from_twilio():
            """Receive audio data from Twilio and send it to the OpenAI Realtime API."""
            nonlocal stream_sid
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    if data['event'] == 'media':
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data['media']['payload']
                        }
                        try:
                            await openai_ws.send(json.dumps(audio_append))
                        except websockets.exceptions.ConnectionClosed:
                            print("OpenAI WebSocket connection closed")
                            break
                    elif data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        print(f"Incoming stream has started {stream_sid}")
            except WebSocketDisconnect:
                print("Client disconnected.")
                if openai_ws.open:
                    await openai_ws.close()

        async def send_to_twilio():
            """Receive events from the OpenAI Realtime API, send audio back to Twilio."""
            nonlocal stream_sid
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    if response['type'] in LOG_EVENT_TYPES:
                        print(f"Received event: {response['type']}", response)
                    if response['type'] == 'session.updated':
                        print("Session updated successfully:", response)
                    if response[
                            'type'] == 'response.audio.delta' and response.get(
                            'delta'):
                        # Audio from OpenAI
                        try:
                            audio_payload = base64.b64encode(
                                base64.b64decode(
                                    response['delta'])).decode('utf-8')
                            audio_delta = {
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {
                                    "payload": audio_payload
                                }
                            }
                            await websocket.send_json(audio_delta)
                        except Exception as e:
                            print(f"Error processing audio data: {e}")
            except Exception as e:
                print(f"Error in send_to_twilio: {e}")

        await asyncio.gather(receive_from_twilio(), send_to_twilio())


async def send_session_update(openai_ws):
    """Send session update to OpenAI WebSocket."""
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {
                "type": "server_vad"
            },
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": SYSTEM_MESSAGE,
            "modalities": ["text", "audio"],
            "temperature": 0.8,
        }
    }
    print('Sending session update:', json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0") 