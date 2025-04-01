import os
import json
import base64
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from dotenv import load_dotenv
import uvicorn
import logging
import traceback

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
# Configuration
OPENAI_API_KEY = os.getenv(
    'OPENAI_API_KEY')  # requires OpenAI Realtime API Access

SYSTEM_MESSAGE = (
" שמך רעות ואת נציגת שירות של אפליקציית 'תוביל אותי', שמתמחה במציאת חברות הובלה ללקוחות. את דוברת עברית ויודעת להציע תמיכה מועילה ונעימה. התשובות שלך צריכות להיות ישירות, חמות וקלות להבנה, ולא להגזים במילים. חשוב להיות קשובה לצרכים של הלקוח ולהגיב בנימה נלהבת אך טבעית, כאילו מדובר בשיחה עם אדם אמיתי ולא עם מערכת אוטומטית. התשובות שלך צריכות להיות פשוטות, ענייניות, עם חיוך ותחושת קבלה, לא יותר מדי פורמליות. תמיד תהיי זמינה לשאלות, ותשני את הטון שלך לפי הצורך של הלקוח – אם הוא צריך עזרה או טיפים למעבר דירה, אם הוא רק רוצה לברר משהו, או אם הוא צריך עזרה בשימוש באפליקציה."

"מיד בתחילת השיחה, שאלי את הלקוח לשמו כדי ליצור קשר אישי, והראי התעניינות כנה. כאשר לקוח זקוק לעזרה במציאת הובלה או בשימוש באפליקציה, הסבירי את התהליך במלואו: קודם צריך להתחבר לאפליקציה, לבחור את הפריטים להובלה מתוך הקטגוריות שבאתר, לסמן את הכמות של כל פריט, ולציין האם נדרש גם פירוק והרכבה לכל פריט. לאחר מכן, יש למלא את פרטי ההובלה ואת היעד. בסיום התהליך, הלקוח יקבל באפליקציה הצעות מחיר ממובילים שונים, והוא יוכל לבחור את המוביל המתאים לו ביותר לפי שיקול דעתו."

"חשוב מאוד: היי קשובה כשהלקוח מנסה להתערב או לקטוע אותך. עצרי מיד את הדיבור שלך כשאת מזהה שהלקוח מנסה לדבר. אל תחזרי על מה שכבר אמרת אחרי שנקטעת. המשיכי משם והתייחסי למה שהלקוח אמר. שמרי על משפטים קצרים וברורים, כדי לאפשר ללקוח להגיב. היי ממוקדת אך ורק בנושאים הקשורים להובלת דירות ולשימוש באפליקציית 'תוביל אותי'. אל תסטי לנושאים אחרים שלא קשורים לתחום זה.")
VOICE = 'shimmer'
LOG_EVENT_TYPES = [
    'response.content.done', 'rate_limits.updated', 'response.done',
    'input_audio_buffer.committed', 'input_audio_buffer.speech_stopped',
    'input_audio_buffer.speech_started', 'session.created'
]

# WebSocket connection constants
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_DELAY = 2  # seconds

app = FastAPI()
if not OPENAI_API_KEY:
    raise ValueError(
        'Missing the OpenAI API key. Please set it in the .env file.')


@app.api_route("/", methods=["GET", "POST"])
async def index_page():
    return "<h1>Server is up and running.Youtube: @the_ai_solopreneur </h1>"


@app.api_route("/test", methods=["GET"])
async def test_endpoint():
    """Test endpoint to check if the server is responsive."""
    return JSONResponse({"status": "ok", "message": "Server is running correctly"})


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call and return TwiML response to connect to Media Stream."""
    try:
        logger.info("Received incoming call request")
        response = VoiceResponse()
        
        # Simplified greeting for testing
        response.say("Welcome", voice="woman")
        response.pause(length=1)
        
        # Get the host for WebSocket connection
        host = request.url.hostname
        logger.info(f"Host for WebSocket connection: {host}")
        
        # Set up streaming
        connect = Connect()
        stream_url = f'wss://{host}/media-stream'
        logger.info(f"Setting up stream URL: {stream_url}")
        connect.stream(url=stream_url)
        response.append(connect)
        
        twiml_response = str(response)
        logger.info(f"Generated TwiML response: {twiml_response}")
        return HTMLResponse(content=twiml_response, media_type="application/xml")
    except Exception as e:
        logger.error(f"Error in incoming-call handler: {str(e)}")
        logger.error(traceback.format_exc())
        response = VoiceResponse()
        response.say("Sorry, there was an error connecting your call.")
        return HTMLResponse(content=str(response), media_type="application/xml")


async def connect_to_openai():
    """Establish connection to OpenAI with retry logic."""
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1"
    }
    
    attempts = 0
    while attempts < MAX_RECONNECT_ATTEMPTS:
        try:
            logger.info(f"Attempting to connect to OpenAI WebSocket (attempt {attempts+1}/{MAX_RECONNECT_ATTEMPTS})")
            conn = await websockets.connect(
                'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01',
                extra_headers=headers,
                ping_interval=20,  # Send ping every 20 seconds to keep connection alive
                ping_timeout=20,   # Wait 20 seconds for pong response
                close_timeout=10   # Wait 10 seconds for close handshake
            )
            logger.info("Successfully connected to OpenAI WebSocket")
            return conn
        except Exception as e:
            attempts += 1
            logger.error(f"Error connecting to OpenAI (attempt {attempts}/{MAX_RECONNECT_ATTEMPTS}): {str(e)}")
            logger.error(traceback.format_exc())
            if attempts < MAX_RECONNECT_ATTEMPTS:
                logger.info(f"Waiting {RECONNECT_DELAY} seconds before retry...")
                await asyncio.sleep(RECONNECT_DELAY)
            else:
                logger.error("Max reconnection attempts reached. Giving up.")
                raise


@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connections between Twilio and OpenAI."""
    logger.info("Received WebSocket connection request")
    
    try:
        await websocket.accept()
        logger.info("WebSocket connection accepted")

        try:
            openai_ws = await connect_to_openai()
            
            await send_session_update(openai_ws)
            stream_sid = None
            
            # Send initial greeting to trigger OpenAI model
            initial_message = {
                "type": "content.text",
                "content": "שלום"
            }
            logger.info("Sending initial greeting to OpenAI")
            await openai_ws.send(json.dumps(initial_message))

            # Store buffered audio data during reconnection
            audio_buffer = []
            connection_active = True

            async def receive_from_twilio():
                """Receive audio data from Twilio and send it to the OpenAI Realtime API."""
                nonlocal stream_sid, connection_active, audio_buffer
                try:
                    async for message in websocket.iter_text():
                        if not connection_active:
                            # Buffer audio data during reconnection
                            if len(audio_buffer) < 100:  # Limit buffer size
                                audio_buffer.append(message)
                            continue

                        data = json.loads(message)
                        if data['event'] == 'media':
                            audio_append = {
                                "type": "input_audio_buffer.append",
                                "audio": data['media']['payload']
                            }
                            try:
                                await openai_ws.send(json.dumps(audio_append))
                            except websockets.exceptions.ConnectionClosed:
                                logger.error("OpenAI WebSocket connection closed unexpectedly")
                                connection_active = False
                                break
                        elif data['event'] == 'start':
                            stream_sid = data['start']['streamSid']
                            logger.info(f"Incoming stream has started {stream_sid}")
                except WebSocketDisconnect:
                    logger.info("Client disconnected.")
                    connection_active = False
                    if openai_ws and not openai_ws.closed:
                        await openai_ws.close()
                except Exception as e:
                    logger.error(f"Error in receive_from_twilio: {str(e)}")
                    logger.error(traceback.format_exc())
                    connection_active = False

            async def send_to_twilio():
                """Receive events from the OpenAI Realtime API, send audio back to Twilio."""
                nonlocal stream_sid, connection_active
                try:
                    async for openai_message in openai_ws:
                        response = json.loads(openai_message)
                        if response['type'] in LOG_EVENT_TYPES:
                            logger.info(f"Received event: {response['type']}")
                            if 'error' in response:
                                logger.error(f"OpenAI error: {response['error']}")
                        if response['type'] == 'session.updated':
                            logger.info("Session updated successfully")
                        if response[
                                'type'] == 'response.audio.delta' and response.get(
                                'delta') and stream_sid:
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
                                logger.error(f"Error processing audio data: {str(e)}")
                                logger.error(traceback.format_exc())
                except websockets.exceptions.ConnectionClosed:
                    logger.error("OpenAI WebSocket connection closed")
                    connection_active = False
                except Exception as e:
                    logger.error(f"Error in send_to_twilio: {str(e)}")
                    logger.error(traceback.format_exc())
                    connection_active = False

            await asyncio.gather(receive_from_twilio(), send_to_twilio())
        finally:
            if 'openai_ws' in locals() and not openai_ws.closed:
                await openai_ws.close()
                logger.info("OpenAI WebSocket connection closed")
                
    except Exception as e:
        logger.error(f"Error in WebSocket handler: {str(e)}")
        logger.error(traceback.format_exc())
        try:
            await websocket.close()
        except:
            pass


async def send_session_update(openai_ws):
    """Send session update to OpenAI WebSocket."""
    try:
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
        logger.info('Sending session update to OpenAI')
        await openai_ws.send(json.dumps(session_update))
        logger.info('Session update sent successfully')
    except Exception as e:
        logger.error(f"Error sending session update: {str(e)}")
        logger.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0") 