import os
import json
import base64
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, Request, Form, HTTPException, Query
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
import time
from datetime import datetime
from typing import Dict, Optional, List, Any
import urllib.parse

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set up templates and static files
templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)

# Check if templates directory exists, create if not
if not os.path.exists(templates_dir):
    os.makedirs(templates_dir)

# Create a directory for audio files if it doesn't exist
audio_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio")
if not os.path.exists(audio_dir):
    os.makedirs(audio_dir)

# Create a directory for uploaded trigger audio if it doesn't exist
uploaded_audio_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploaded_audio")
if not os.path.exists(uploaded_audio_dir):
    os.makedirs(uploaded_audio_dir)
    logger.info(f"Created directory for uploaded audio at {uploaded_audio_dir}")

# Path to the trigger audio file - this will be created if it doesn't exist
TRIGGER_AUDIO_PATH = os.path.join(audio_dir, "trigger.txt")

# Dictionary to store call information
active_calls: Dict[str, Dict] = {}

# Create a silent audio file in base64 format if it doesn't exist
# This is a short segment of silence in G.711 u-law format
def create_silent_audio_file():
    if not os.path.exists(TRIGGER_AUDIO_PATH):
        # This is a base64-encoded representation of a short segment of silence in G.711 u-law format
        silent_audio_base64 = "//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C"
        with open(TRIGGER_AUDIO_PATH, 'w') as f:
            f.write(silent_audio_base64)
        logger.info(f"Created silent audio file at {TRIGGER_AUDIO_PATH}")
    else:
        logger.info(f"Silent audio file already exists at {TRIGGER_AUDIO_PATH}")

# Read the trigger audio file
def get_trigger_audio():
    try:
        with open(TRIGGER_AUDIO_PATH, 'r') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error reading trigger audio file: {str(e)}")
        # Return a fallback silent audio segment if the file can't be read
        return "//7/Av/+/wL//v8C//7/Av/+/wL//v8C"

# Create the silent audio file when the server starts
create_silent_audio_file()

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

# Base system message template
SYSTEM_MESSAGE_TEMPLATE = """
שמך רעות ואת נציגת שירות של אפליקציית 'תוביל אותי', שמתמחה במציאת חברות הובלה ללקוחות. את דוברת עברית ויודעת להציע תמיכה מועילה ונעימה. התשובות שלך צריכות להיות ישירות, חמות וקלות להבנה, ולא להגזים במילים. חשוב להיות קשובה לצרכים של הלקוח ולהגיב בנימה נלהבת אך טבעית, כאילו מדובר בשיחה עם אדם אמיתי ולא עם מערכת אוטומטית. התשובות שלך צריכות להיות פשוטות, ענייניות, עם חיוך ותחושת קבלה, לא יותר מדי פורמליות. תמיד תהיי זמינה לשאלות, ותשני את הטון שלך לפי הצורך של הלקוח – אם הוא צריך עזרה או טיפים למעבר דירה, אם הוא רק רוצה לברר משהו, או אם הוא צריך עזרה בשימוש באפליקציה.

מיד בתחילת השיחה, {name_instruction} והראי התעניינות כנה. כאשר לקוח זקוק לעזרה במציאת הובלה או בשימוש באפליקציה, הסבירי את התהליך במלואו: קודם צריך להתחבר לאפליקציה, לבחור את הפריטים להובלה מתוך הקטגוריות שבאתר, לסמן את הכמות של כל פריט, ולציין האם נדרש גם פירוק והרכבה לכל פריט. לאחר מכן, יש למלא את פרטי ההובלה ואת היעד. בסיום התהליך, הלקוח יקבל באפליקציה הצעות מחיר ממובילים שונים, והוא יוכל לבחור את המוביל המתאים לו ביותר לפי שיקול דעתו.

חשוב מאוד: היי קשובה כשהלקוח מנסה להתערב או לקטוע אותך. עצרי מיד את הדיבור שלך כשאת מזהה שהלקוח מנסה לדבר. אל תחזרי על מה שכבר אמרת אחרי שנקטעת. המשיכי משם והתייחסי למה שהלקוח אמר. שמרי על משפטים קצרים וברורים, כדי לאפשר ללקוח להגיב. היי ממוקדת אך ורק בנושאים הקשורים להובלת דירות ולשימוש באפליקציית 'תוביל אותי'. אל תסטי לנושאים אחרים שלא קשורים לתחום זה.

בשיחות יוצאות, כשאת מתקשרת ללקוח: התחילי לדבר מיד ברגע שהשיחה מתחברת, בלי לחכות שהלקוח ידבר קודם. {greeting_instruction}
"""

# Get the system message with the recipient name if available
def get_system_message(recipient_name=None):
    if recipient_name:
        name_instruction = f"פני ללקוח בשמו '{recipient_name}' כדי ליצור קשר אישי"
        greeting_instruction = f"הציגי את עצמך: 'שלום {recipient_name}, זו רעות מאפליקציית תוביל אותי, אני מתקשרת לבדוק האם אתה מעוניין בשירותי הובלה?' והמשיכי את השיחה בהתאם לתגובת הלקוח."
    else:
        name_instruction = "שאלי את הלקוח לשמו כדי ליצור קשר אישי"
        greeting_instruction = "הציגי את עצמך: 'שלום, זו רעות מאפליקציית תוביל אותי, אני מתקשרת לבדוק האם אתה מעוניין בשירותי הובלה?' והמשיכי את השיחה בהתאם לתגובת הלקוח."
    
    return SYSTEM_MESSAGE_TEMPLATE.format(
        name_instruction=name_instruction,
        greeting_instruction=greeting_instruction
    )

# Default system message (without recipient name)
SYSTEM_MESSAGE = get_system_message()

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

# Helper function to make dictionaries JSON-serializable
def serialize_for_json(obj: Any) -> Any:
    """Convert non-serializable objects to serializable ones."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [serialize_for_json(item) for item in obj]
    return obj

# Endpoint to check call status
@app.get("/call-status")
async def get_call_status(call_sid: str = Query(...)):
    """Get the status of a call by SID."""
    try:
        if not twilio_client:
            return JSONResponse({
                "status": "error", 
                "detail": "Twilio client not configured"
            })
        
        # First check our local records
        if call_sid in active_calls:
            call_info = active_calls[call_sid]
            
            # Calculate duration if call is completed
            if "end_time" in call_info and "start_time" in call_info:
                call_info["duration"] = int((call_info["end_time"] - call_info["start_time"]).total_seconds())
            
            # Make sure all data is JSON-serializable
            serialized_call_info = serialize_for_json(call_info)
            return JSONResponse(serialized_call_info)
        
        # If not found locally, fetch from Twilio
        call = twilio_client.calls(call_sid).fetch()
        
        # Calculate duration if available
        duration = None
        if call.duration:
            duration = int(call.duration)
        
        status = call.status.lower()
        
        # Store in active calls
        active_calls[call_sid] = {
            "status": status,
            "duration": duration
        }
        
        return JSONResponse({
            "status": status,
            "duration": duration
        })
    except Exception as e:
        logger.error(f"Error fetching call status: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse({
            "status": "error",
            "detail": str(e)
        }, status_code=500)

@app.api_route("/make-call", methods=["POST"])
async def make_outgoing_call(
    request: Request,
    phone_number: str = Form(...),
    webhook_url: str = Form(None),
    recipient_name: str = Form(None),
    trigger_audio: str = Form(None)
):
    """Initiate an outgoing call to the specified phone number."""
    try:
        if not twilio_client:
            raise HTTPException(status_code=500, detail="Twilio client not configured")
        
        # Clean the phone number to ensure it's in E.164 format
        if not phone_number.startswith('+'):
            phone_number = '+' + phone_number
        
        # Get the host URL for webhooks if not provided
        if not webhook_url:
            # This assumes the request is coming through a proxy that sets the Host header
            webhook_url = request.headers.get('host')
            if webhook_url:
                scheme = "https" if request.url.scheme == "https" else "http"
                webhook_url = f"{scheme}://{webhook_url}"
            else:
                webhook_url = "https://your-app-url.com"
        
        # Store custom trigger audio if provided
        custom_audio_path = None
        if trigger_audio and len(trigger_audio) > 0:
            # Generate a unique filename for this audio
            timestamp = int(time.time())
            custom_audio_path = os.path.join(uploaded_audio_dir, f"trigger_{timestamp}.txt")
            
            # Save the audio file
            try:
                with open(custom_audio_path, 'w') as f:
                    f.write(trigger_audio)
                
                logger.info(f"Saved custom trigger audio to {custom_audio_path} ({len(trigger_audio)} bytes)")
            except Exception as e:
                logger.error(f"Error saving trigger audio: {str(e)}")
                logger.error(traceback.format_exc())
                custom_audio_path = None
        
        # Parameters to pass to the call handler
        params = {}
        if recipient_name:
            params["recipient_name"] = recipient_name
            logger.info(f"Call will use recipient name: {recipient_name}")
        
        if custom_audio_path:
            params["custom_audio_path"] = os.path.basename(custom_audio_path)
            logger.info(f"Call will use custom audio: {os.path.basename(custom_audio_path)}")
        
        # Build the URL with properly encoded query parameters
        media_url = f"{webhook_url}/outgoing-call-handler"
        if params:
            # Properly URL-encode each parameter, especially for non-ASCII characters
            encoded_params = []
            for key, value in params.items():
                encoded_key = urllib.parse.quote(key)
                encoded_value = urllib.parse.quote(value)
                encoded_params.append(f"{encoded_key}={encoded_value}")
            
            query_string = "&".join(encoded_params)
            media_url = f"{media_url}?{query_string}"
        
        logger.info(f"Initiating outgoing call to {phone_number}")
        logger.info(f"Using webhook URL: {media_url}")
        
        # Capture start time
        start_time = datetime.now()
        
        # Make the call using Twilio's API
        call = twilio_client.calls.create(
            to=phone_number,
            from_=TWILIO_PHONE_NUMBER,
            url=media_url,
            # Optional parameters
            # record=True,  # Record the call
            # timeout=30,   # Call timeout in seconds
        )
        
        # Store call information
        active_calls[call.sid] = {
            "status": "initiated",
            "phone": phone_number,
            "recipient_name": recipient_name,
            "start_time": start_time
        }
        
        logger.info(f"Call initiated with SID: {call.sid}")
        
        # Use the serialize_for_json function for the response
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
async def handle_outgoing_call(
    request: Request,
    recipient_name: Optional[str] = None,
    custom_audio_path: Optional[str] = None
):
    """Handle the outgoing call once it's answered."""
    try:
        logger.info("Outgoing call connected")
        
        # Log the parameters received
        logger.info(f"Recipient name: {recipient_name}")
        logger.info(f"Custom audio path: {custom_audio_path}")
        
        # Capture call SID if available
        call_sid = None
        if request.query_params.get("CallSid"):
            call_sid = request.query_params.get("CallSid")
            logger.info(f"Call SID from Twilio: {call_sid}")
            
            # Update call status if we're tracking it
            if call_sid in active_calls:
                active_calls[call_sid]["status"] = "in-progress"
                active_calls[call_sid]["answer_time"] = datetime.now()
        
        response = VoiceResponse()
        
        # Clearer Hebrew greeting for outgoing calls with pause
        greeting = "שלום, מתחברים לשיחה. רגע בבקשה."
        if recipient_name:
            greeting = f"שלום {recipient_name}, מתחברים לשיחה. רגע בבקשה."
            
        response.say(greeting, language="he-IL", voice="woman")
        response.pause(length=2)  # Longer pause to ensure the connection is established
        
        # Get the host for WebSocket connection
        host = request.url.hostname
        logger.info(f"Host for WebSocket connection: {host}")
        
        # Build WebSocket URL with properly encoded parameters
        stream_params = ["direction=outgoing"]
        if recipient_name:
            stream_params.append(f"recipient_name={urllib.parse.quote(recipient_name)}")
        if custom_audio_path:
            stream_params.append(f"custom_audio_path={urllib.parse.quote(custom_audio_path)}")
        if call_sid:
            stream_params.append(f"call_sid={urllib.parse.quote(call_sid)}")
            
        query_string = "&".join(stream_params)
        
        # Set up streaming with parameters
        connect = Connect()
        stream_url = f'wss://{host}/media-stream?{query_string}'
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
        
        # Capture call SID if available
        call_sid = None
        if request.query_params.get("CallSid"):
            call_sid = request.query_params.get("CallSid")
            logger.info(f"Incoming call SID from Twilio: {call_sid}")
            
            # Track call
            active_calls[call_sid] = {
                "status": "in-progress",
                "direction": "incoming",
                "start_time": datetime.now()
            }
        
        response = VoiceResponse()
        
        # Simplified greeting for testing
        response.say("Welcome", voice="woman")
        response.pause(length=1)
        
        # Get the host for WebSocket connection
        host = request.url.hostname
        logger.info(f"Host for WebSocket connection: {host}")
        
        # Parameters for the stream URL
        stream_params = ["direction=incoming"]
        if call_sid:
            stream_params.append(f"call_sid={call_sid}")
            
        query_string = "&".join(stream_params)
        
        # Set up streaming with call direction parameter
        connect = Connect()
        stream_url = f'wss://{host}/media-stream?{query_string}'
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
        
        # URL-decode the parameters
        recipient_name = None
        if "recipient_name" in query_params:
            recipient_name = urllib.parse.unquote(query_params.get("recipient_name"))
            
        custom_audio_path = None
        if "custom_audio_path" in query_params:
            custom_audio_path = urllib.parse.unquote(query_params.get("custom_audio_path"))
            
        call_sid = None
        if "call_sid" in query_params:
            call_sid = urllib.parse.unquote(query_params.get("call_sid"))
        
        logger.info(f"Call direction: {call_direction}")
        logger.info(f"Recipient name: {recipient_name}")
        logger.info(f"Custom audio path: {custom_audio_path}")
        logger.info(f"Call SID: {call_sid}")
        
        await websocket.accept()
        logger.info("WebSocket connection accepted")

        try:
            openai_ws = await connect_to_openai()
            
            # First send session update to configure the connection with call direction and recipient name
            await send_session_update(openai_ws, call_direction, recipient_name)
            stream_sid = None
            
            # Wait for session to initialize
            await asyncio.sleep(2)
            
            # Flag to track if we've triggered AI speech for outgoing calls
            speech_triggered = False
            
            # Store buffered audio data during reconnection
            audio_buffer = []
            connection_active = True

            async def receive_from_twilio():
                """Receive audio data from Twilio and send it to the OpenAI Realtime API."""
                nonlocal stream_sid, connection_active, audio_buffer, speech_triggered
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
                            logger.info(f"Stream has started: {stream_sid}")
                            
                            # For outgoing calls, trigger AI to speak once we have stream_sid
                            if call_direction == "outgoing" and not speech_triggered and stream_sid:
                                await asyncio.sleep(1)  # Give a short delay for connection to stabilize
                                
                                try:
                                    logger.info("=== INITIATING AGGRESSIVE AI SPEECH TRIGGERING SEQUENCE ===")
                                    
                                    # Create greeting text based on recipient name
                                    greeting = "שלום, זו רעות מאפליקציית תוביל אותי" 
                                    if recipient_name:
                                        greeting = f"שלום {recipient_name}, זו רעות מאפליקציית תוביל אותי"
                                    
                                    # Send a direct message to the AI to speak
                                    trigger_messages = [
                                        # First message to set user intent
                                        {
                                            "type": "message",
                                            "message": {
                                                "role": "user",
                                                "content": "תתחילי לדבר עכשיו בבקשה. אל תחכי לי שאדבר."
                                            }
                                        },
                                        # Force AI to say hello (direct speech command)
                                        {
                                            "type": "content.speech",
                                            "content": greeting
                                        },
                                        # Force another speech continuation
                                        {
                                            "type": "content.speech",
                                            "content": "אני מתקשרת לבדוק האם אתה מעוניין בשירותי הובלה?"
                                        },
                                        # Final fallback - direct text trigger
                                        {
                                            "type": "content.text",
                                            "content": "האם אתה צריך עזרה במציאת חברת הובלה?"
                                        }
                                    ]
                                    
                                    # Send all trigger messages with short delays
                                    for i, msg in enumerate(trigger_messages):
                                        logger.info(f"Sending trigger message {i+1}/{len(trigger_messages)}: {msg['type']}")
                                        await openai_ws.send(json.dumps(msg))
                                        await asyncio.sleep(0.5)
                                    
                                    # Mark as triggered
                                    speech_triggered = True
                                    logger.info("All AI speech triggers sent for outgoing call")
                                    
                                except Exception as e:
                                    logger.error(f"Error triggering AI speech: {e}")
                                    logger.error(traceback.format_exc())
                        elif data['event'] == 'stop':
                            logger.info("Call has been disconnected")
                            
                            # Update call status if we have the call_sid
                            if call_sid and call_sid in active_calls:
                                active_calls[call_sid]["status"] = "completed"
                                active_calls[call_sid]["end_time"] = datetime.now()
                                
                                # Calculate duration
                                if "start_time" in active_calls[call_sid]:
                                    start_time = active_calls[call_sid]["start_time"]
                                    active_calls[call_sid]["duration"] = int(
                                        (datetime.now() - start_time).total_seconds()
                                    )
                                    logger.info(f"Call duration: {active_calls[call_sid]['duration']} seconds")
                                
                except WebSocketDisconnect:
                    logger.info("Client disconnected.")
                    connection_active = False
                    
                    # Update call status if disconnected
                    if call_sid and call_sid in active_calls:
                        active_calls[call_sid]["status"] = "completed"
                        active_calls[call_sid]["end_time"] = datetime.now()
                        
                        # Calculate duration
                        if "start_time" in active_calls[call_sid]:
                            start_time = active_calls[call_sid]["start_time"]
                            active_calls[call_sid]["duration"] = int(
                                (datetime.now() - start_time).total_seconds()
                            )
                    
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


async def send_session_update(openai_ws, call_direction="incoming", recipient_name=None):
    """Send session update to OpenAI WebSocket."""
    try:
        # For outgoing calls, prioritize audio over text for immediate speaking
        modalities = ["text", "audio"] if call_direction == "incoming" else ["audio", "text"]
        
        # Get the system message with recipient name if provided
        system_message = get_system_message(recipient_name)
        
        session_update = {
            "type": "session.update",
            "session": {
                "turn_detection": {
                    "type": "server_vad"
                },
                "input_audio_format": "g711_ulaw",
                "output_audio_format": "g711_ulaw",
                "voice": VOICE,
                "instructions": system_message,
                "modalities": modalities,
                "temperature": 0.8,
            }
        }
        logger.info(f'Sending session update to OpenAI for {call_direction} call')
        logger.info(f'Using modalities order: {modalities}')
        if recipient_name:
            logger.info(f'Using recipient name: {recipient_name}')
            
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