import os
import json
import base64
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from twilio.rest import Client
from dotenv import load_dotenv
import uvicorn
import logging
import traceback
import random

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set up templates and static files
templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)

# Check if templates directory exists, create if not
if not os.path.exists(templates_dir):
    os.makedirs(templates_dir)

load_dotenv()
# Configuration
OPENAI_API_KEY = os.getenv(
    'OPENAI_API_KEY')  # requires OpenAI Realtime API Access
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

# Initialize Twilio client if credentials are available
twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

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

# Check if Twilio credentials are available
if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
    logger.warning('Twilio credentials not fully configured. Outgoing calls will not work.')

@app.api_route("/", methods=["GET", "POST"])
async def index_page():
    return "<h1>Server is up and running. <a href='/call-form'>Make a call</a></h1>"

@app.get("/call-form", response_class=HTMLResponse)
async def get_call_form(request: Request):
    """Render the form to make outgoing calls."""
    try:
        return templates.TemplateResponse("make_call.html", {"request": request})
    except Exception as e:
        logger.error(f"Error rendering call form: {str(e)}")
        return HTMLResponse(content=f"<h1>Error loading form: {str(e)}</h1>")

@app.api_route("/test", methods=["GET"])
async def test_endpoint():
    """Test endpoint to check if the server is responsive."""
    return JSONResponse({"status": "ok", "message": "Server is running correctly"})


@app.api_route("/make-call", methods=["POST"])
async def make_outgoing_call(phone_number: str = Form(...), webhook_url: str = Form(None)):
    """Initiate an outgoing call to the specified phone number."""
    try:
        if not twilio_client:
            raise HTTPException(status_code=500, detail="Twilio client not configured")
        
        # Clean the phone number to ensure it's in E.164 format
        # This is a simple check - proper phone validation would be more complex
        if not phone_number.startswith('+'):
            phone_number = '+' + phone_number
        
        # Get the host URL for webhooks if not provided
        if not webhook_url:
            # This assumes the request is coming through a proxy that sets the Host header
            webhook_url = "https://your-app-url.com"
        
        # The URL for Twilio to connect back to our media endpoint
        media_url = f"{webhook_url}/outgoing-call-handler"
        
        logger.info(f"Initiating outgoing call to {phone_number}")
        
        # Make the call using Twilio's API
        call = twilio_client.calls.create(
            to=phone_number,
            from_=TWILIO_PHONE_NUMBER,
            url=media_url,
            # Optional parameters
            # record=True,  # Record the call
            # timeout=30,   # Call timeout in seconds
        )
        
        logger.info(f"Call initiated with SID: {call.sid}")
        
        return JSONResponse({
            "status": "success",
            "message": "Call initiated",
            "call_sid": call.sid
        })
        
    except Exception as e:
        logger.error(f"Error making outgoing call: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Error making call: {str(e)}")


@app.api_route("/outgoing-call-handler", methods=["GET", "POST"])
async def handle_outgoing_call(request: Request):
    """Handle the outgoing call once it's answered."""
    try:
        logger.info("Outgoing call connected")
        response = VoiceResponse()
        
        # Clearer Hebrew greeting for outgoing calls with pause
        response.say("שלום, מתחברים לשיחה. רגע בבקשה.", language="he-IL", voice="woman")
        response.pause(length=2)  # Longer pause to ensure the connection is established
        
        # Get the host for WebSocket connection
        host = request.url.hostname
        logger.info(f"Host for WebSocket connection: {host}")
        
        # Set up streaming with call direction parameter to indicate outgoing call
        connect = Connect()
        stream_url = f'wss://{host}/media-stream?direction=outgoing'
        logger.info(f"Setting up stream URL: {stream_url}")
        connect.stream(url=stream_url)
        response.append(connect)
        
        twiml_response = str(response)
        logger.info(f"Generated TwiML response: {twiml_response}")
        return HTMLResponse(content=twiml_response, media_type="application/xml")
    except Exception as e:
        logger.error(f"Error in outgoing-call handler: {str(e)}")
        logger.error(traceback.format_exc())
        response = VoiceResponse()
        response.say("Sorry, there was an error connecting your call.")
        return HTMLResponse(content=str(response), media_type="application/xml")


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
        
        # Set up streaming with call direction parameter
        connect = Connect()
        stream_url = f'wss://{host}/media-stream?direction=incoming'
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
                'wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview',
                extra_headers=headers,
                ping_interval=5,  # Send ping every 5 seconds to keep connection alive
                ping_timeout=20,   # Wait 20 seconds for pong response
                close_timeout=10,   # Wait 10 seconds for close handshake
                max_size=None,     # No limit on message size
                max_queue=32       # Increase queue size
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
        # Get query parameters 
        query_params = websocket.query_params
        call_direction = query_params.get("direction", "incoming")
        logger.info(f"Call direction: {call_direction}")
        
        await websocket.accept()
        logger.info("WebSocket connection accepted")

        try:
            openai_ws = await connect_to_openai()
            
            # First send session update to configure the connection
            await send_session_update(openai_ws)
            stream_sid = None
            
            # Wait longer for the session to initialize fully for outgoing calls
            if call_direction == "outgoing":
                await asyncio.sleep(3)
            else:
                await asyncio.sleep(2)
            
            # For outgoing calls, send initial message to start the conversation
            if call_direction == "outgoing" and openai_ws and not openai_ws.closed:
                logger.info("Sending initial content for outgoing call")
                
                # First trigger with content.text format
                initial_text = {
                    "type": "content.text",
                    "content": "שלום, זו רעות מאפליקציית 'תוביל אותי'. אני מתקשרת לבדוק אם אתה מעוניין בשירותי הובלה. האם זה זמן טוב לשיחה?"
                }
                await openai_ws.send(json.dumps(initial_text))
                logger.info("Initial text content sent for outgoing call")
                
                # Give it a moment to process
                await asyncio.sleep(0.5)
                
                # Then follow up with another message to ensure it speaks
                follow_up = {
                    "type": "message",
                    "message": {
                        "role": "user",
                        "content": "בבקשה ספרי לי על שירותי ההובלה שלכם"
                    }
                }
                await openai_ws.send(json.dumps(follow_up))
                logger.info("Follow up message sent for outgoing call")
            else:
                # No initial message for incoming calls - wait for user to speak
                logger.info("Session initialized, waiting for audio from Twilio")

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
                                # Log the first few audio packets to debug format issues
                                if stream_sid and stream_sid.startswith("M") and len(audio_buffer) < 5:
                                    logger.info(f"Sending audio packet to OpenAI (sample): {data['media']['payload'][:20]}...")
                                
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
                        
                        # Log all events for better debugging
                        logger.info(f"OpenAI event: {response['type']}")
                        
                        if response['type'] in LOG_EVENT_TYPES:
                            if 'error' in response:
                                logger.error(f"OpenAI error: {response['error']}")
                        
                        if response['type'] == 'session.updated':
                            logger.info("Session updated successfully")
                            
                        if response['type'] == 'response.content.delta':
                            logger.info(f"Content delta received: {response.get('delta', '')}")
                        
                        if response['type'] == 'response.audio.delta' and response.get('delta') and stream_sid:
                            # Audio from OpenAI
                            try:
                                # Log every 50th audio packet to avoid excessive logging
                                if random.randint(1, 50) == 1:
                                    logger.info("Audio delta received from OpenAI")
                                
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
        
        # Wait a moment for the session to initialize properly
        await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Error sending session update: {str(e)}")
        logger.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0") 