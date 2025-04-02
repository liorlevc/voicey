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

# Create a directory for call transcripts if it doesn't exist
transcripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcripts")
if not os.path.exists(transcripts_dir):
    os.makedirs(transcripts_dir)
    logger.info(f"Created directory for call transcripts at {transcripts_dir}")

# Path to the trigger audio file - this will be created if it doesn't exist
TRIGGER_AUDIO_PATH = os.path.join(audio_dir, "trigger.txt")

# Dictionary to store call information
active_calls: Dict[str, Dict] = {}

# Create a silent audio file in base64 format if it doesn't exist
# This is a short segment of silence in G.711 u-law format
def create_silent_audio_file():
    if not os.path.exists(TRIGGER_AUDIO_PATH):
        # This is a base64-encoded representation of a short segment of silence in G.711 u-law format
        silent_audio_base64 = "//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C//7/Av/+/wL//v8C"
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
שמך מיכל, את נציגת שירות טלפוני, כל מי שפותח איתך שיחה, תעני שלום בנימוס ותציגי את עצמך, תציעי למי שמדבר איתך הצעה מעניינת למעבר דירה ותבררי האם זה רלוונטי והאם הוא מעוניין לשמוע, אם הוא לא מעוניין לשמוע אל תמשיכי בשיחה ואל תסבירי במה מדובר, אם הוא מעוניין לשמוע, תספרי לו על כך שהוא יכול להשתמש באפליקציית תוביל אותי להובלת דירה בראש שקט, המטרה שלך היא להיות נחמדה, נלהבת, סוחפת אבל עניינית, מקצועית, ולא לחשוף מידע אם הלקוח אינו מסכים לשמוע על ההצעה

בשיחות יוצאות, כשאת מתקשרת ללקוח: התחילי לדבר מיד ברגע שהשיחה מתחברת, בלי לחכות שהלקוח ידבר קודם. {greeting_instruction}
"""

# Get the system message with the recipient name if available
def get_system_message(recipient_name=None):
    if recipient_name:
        greeting_instruction = "הציגי את עצמך: 'שלום מדברת מיכל, אני מתקשרת בכדי לברר האם אתה מתכנן מעבר דירה בקרוב? והאם תרצה לשמוע את ההצעה?' והמשיכי את השיחה בהתאם לתגובת הלקוח."
    else:
        greeting_instruction = "הציגי את עצמך: 'שלום מדברת מיכל, אני מתקשרת בכדי לברר האם אתה מתכנן מעבר דירה בקרוב? והאם תרצה לשמוע את ההצעה?' והמשיכי את השיחה בהתאם לתגובת הלקוח."
    
    return SYSTEM_MESSAGE_TEMPLATE.format(
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

# Endpoint to terminate an active call
@app.post("/terminate-call")
async def terminate_call(call_sid: str = Form(...)):
    """Terminate an active call by SID."""
    try:
        if not twilio_client:
            return JSONResponse({
                "status": "error", 
                "detail": "Twilio client not configured"
            })
        
        logger.info(f"Attempting to terminate call: {call_sid}")
        
        # Terminate the call via Twilio API
        call = twilio_client.calls(call_sid).update(status="completed")
        
        # Update our local records
        if call_sid in active_calls:
            active_calls[call_sid]["status"] = "completed"
            active_calls[call_sid]["end_time"] = datetime.now()
            
            # Calculate duration
            if "start_time" in active_calls[call_sid]:
                start_time = active_calls[call_sid]["start_time"]
                active_calls[call_sid]["duration"] = int(
                    (datetime.now() - start_time).total_seconds()
                )
        
        return JSONResponse({
            "status": "success",
            "message": f"Call {call_sid} has been terminated"
        })
    except Exception as e:
        logger.error(f"Error terminating call: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse({
            "status": "error",
            "detail": str(e)
        }, status_code=500)

# Endpoint to clear all queued calls
@app.post("/clear-call-queue")
async def clear_call_queue():
    """Cancel all queued calls."""
    try:
        if not twilio_client:
            return JSONResponse({
                "status": "error", 
                "detail": "Twilio client not configured"
            })
        
        logger.info("Attempting to clear call queue")
        
        # Get all queued calls
        calls = twilio_client.calls.list(status="queued")
        
        cancelled_count = 0
        for call in calls:
            # Cancel each queued call
            twilio_client.calls(call.sid).update(status="canceled")
            
            # Update our local records if we're tracking this call
            if call.sid in active_calls:
                active_calls[call.sid]["status"] = "canceled"
                active_calls[call.sid]["end_time"] = datetime.now()
            
            cancelled_count += 1
        
        return JSONResponse({
            "status": "success",
            "message": f"Cleared {cancelled_count} calls from queue"
        })
    except Exception as e:
        logger.error(f"Error clearing call queue: {str(e)}")
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
    trigger_audio: str = Form(None),
    custom_script: str = Form(None)
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
        
        # Store custom script if provided
        custom_script_path = None
        if custom_script and len(custom_script) > 0:
            # Create scripts directory if it doesn't exist
            scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
            if not os.path.exists(scripts_dir):
                os.makedirs(scripts_dir)
                logger.info(f"Created directory for custom scripts at {scripts_dir}")
            
            # Generate a unique filename for this script
            timestamp = int(time.time())
            custom_script_path = os.path.join(scripts_dir, f"script_{timestamp}.txt")
            
            # Save the script file
            try:
                with open(custom_script_path, 'w') as f:
                    f.write(custom_script)
                
                logger.info(f"Saved custom script to {custom_script_path} ({len(custom_script)} bytes)")
            except Exception as e:
                logger.error(f"Error saving custom script: {str(e)}")
                logger.error(traceback.format_exc())
                custom_script_path = None
        
        # Parameters to pass to the call handler
        params = {}
        if recipient_name:
            params["recipient_name"] = recipient_name
            logger.info(f"Call will use recipient name: {recipient_name}")
        
        if custom_audio_path:
            params["custom_audio_path"] = os.path.basename(custom_audio_path)
            logger.info(f"Call will use custom audio: {os.path.basename(custom_audio_path)}")
            
        if custom_script_path:
            params["custom_script_path"] = os.path.basename(custom_script_path)
            logger.info(f"Call will use custom script: {os.path.basename(custom_script_path)}")
        
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
    custom_audio_path: Optional[str] = None,
    custom_script_path: Optional[str] = None
):
    """Handle the outgoing call once it's answered."""
    try:
        logger.info("Outgoing call connected")
        
        # Log the parameters received
        logger.info(f"Recipient name: {recipient_name}")
        logger.info(f"Custom audio path: {custom_audio_path}")
        logger.info(f"Custom script path: {custom_script_path}")
        
        # Capture call SID if available
        call_sid = None
        if request.query_params.get("CallSid"):
            call_sid = request.query_params.get("CallSid")
            logger.info(f"Call SID from Twilio: {call_sid}")
            
            # Update call status if we're tracking it
            if call_sid in active_calls:
                active_calls[call_sid]["status"] = "in-progress"
                active_calls[call_sid]["answer_time"] = datetime.now()
                
                # Store script path if provided
                if custom_script_path:
                    active_calls[call_sid]["custom_script_path"] = custom_script_path
        
        response = VoiceResponse()
        
        # Clearer Hebrew greeting for outgoing calls with pause
        greeting = "שלום, מתחברים לשיחה. רגע בבקשה."
        if recipient_name:
            greeting = "שלום, מתחברים לשיחה. רגע בבקשה."
            
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
        if custom_script_path:
            stream_params.append(f"custom_script_path={urllib.parse.quote(custom_script_path)}")
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
        
        custom_script_path = None
        if "custom_script_path" in query_params:
            custom_script_path = urllib.parse.unquote(query_params.get("custom_script_path"))
            
        call_sid = None
        if "call_sid" in query_params:
            call_sid = urllib.parse.unquote(query_params.get("call_sid"))
        
        logger.info(f"Call direction: {call_direction}")
        logger.info(f"Recipient name: {recipient_name}")
        logger.info(f"Custom audio path: {custom_audio_path}")
        logger.info(f"Custom script path: {custom_script_path}")
        logger.info(f"Call SID: {call_sid}")
        
        await websocket.accept()
        logger.info("WebSocket connection accepted")

        try:
            openai_ws = await connect_to_openai()
            
            # First send session update to configure the connection with call direction and recipient name
            await send_session_update(openai_ws, call_direction, recipient_name, custom_script_path)
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
                                    greeting = "שלום מדברת מיכל, אני מתקשרת בכדי לברר האם אתה מתכנן מעבר דירה בקרוב? והאם תרצה לשמוע את ההצעה?" 
                                    if recipient_name:
                                        greeting = "שלום מדברת מיכל, אני מתקשרת בכדי לברר האם אתה מתכנן מעבר דירה בקרוב? והאם תרצה לשמוע את ההצעה?"
                                    
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
                                        # Final fallback - direct text trigger
                                        {
                                            "type": "content.text",
                                            "content": "האם אתה מתכנן מעבר דירה בקרוב?"
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
                    # Initialize transcripts for this call if we have a call SID
                    call_transcript = []
                    transcript_file = None
                    if call_sid:
                        # Create a transcript file with timestamp
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        transcript_file = os.path.join(transcripts_dir, f"call_{call_sid}_{timestamp}.txt")
                        
                        # Initialize transcript file with call info
                        with open(transcript_file, 'w') as f:
                            call_direction_str = "Outgoing" if call_direction == "outgoing" else "Incoming"
                            f.write(f"=== {call_direction_str} CALL TRANSCRIPT ===\n")
                            f.write(f"Call SID: {call_sid}\n")
                            f.write(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                            if recipient_name:
                                f.write(f"Recipient: {recipient_name}\n")
                            f.write("===================================\n\n")
                            
                        # Store transcript file path in active_calls
                        if call_sid in active_calls:
                            active_calls[call_sid]["transcript_file"] = transcript_file
                    
                    async for openai_message in openai_ws:
                        response = json.loads(openai_message)
                        
                        # Log all events for better debugging
                        logger.info(f"OpenAI event: {response['type']}")
                        
                        # Record transcripts
                        if response['type'] == 'response.audio_transcript.delta' and response.get('delta'):
                            # This is a transcript of what the user said
                            transcript_text = response.get('delta', '')
                            logger.info(f"USER SPEECH: {transcript_text}")
                            
                            # Save to transcript file if available
                            if transcript_file and transcript_text:
                                with open(transcript_file, 'a') as f:
                                    f.write(f"USER: {transcript_text}\n")
                                
                                # Store in active calls
                                if call_sid in active_calls:
                                    if "transcript" not in active_calls[call_sid]:
                                        active_calls[call_sid]["transcript"] = []
                                    active_calls[call_sid]["transcript"].append({"role": "user", "content": transcript_text})
                        
                        if response['type'] == 'response.content.delta' and response.get('delta'):
                            # This is AI's response text
                            content_text = response.get('delta', '')
                            logger.info(f"AI RESPONSE: {content_text}")
                            
                            # Save to transcript file if available
                            if transcript_file and content_text:
                                with open(transcript_file, 'a') as f:
                                    f.write(f"AI: {content_text}\n")
                                
                                # Store in active calls
                                if call_sid in active_calls:
                                    if "transcript" not in active_calls[call_sid]:
                                        active_calls[call_sid]["transcript"] = []
                                    active_calls[call_sid]["transcript"].append({"role": "assistant", "content": content_text})
                        
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


async def send_session_update(openai_ws, call_direction="incoming", recipient_name=None, custom_script_path=None):
    """Send session update to OpenAI WebSocket."""
    try:
        # For outgoing calls, prioritize audio over text for immediate speaking
        modalities = ["text", "audio"] if call_direction == "incoming" else ["audio", "text"]
        
        # Get custom script if provided
        system_message = None
        if custom_script_path:
            scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
            full_script_path = os.path.join(scripts_dir, custom_script_path)
            if os.path.exists(full_script_path):
                try:
                    with open(full_script_path, 'r') as f:
                        system_message = f.read().strip()
                    logger.info(f"Using custom script from {custom_script_path}")
                except Exception as e:
                    logger.error(f"Error reading custom script: {str(e)}")
                    logger.error(traceback.format_exc())
        
        # Fall back to default if no custom script was provided or could be read
        if not system_message:
            system_message = get_system_message(recipient_name)
            logger.info("Using default system message")
        
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

# Endpoint to get call transcript
@app.get("/call-transcript")
async def get_call_transcript(call_sid: str = Query(...)):
    """Get the transcript of a call by SID."""
    try:
        # Check if we have the call in our records
        if call_sid in active_calls and "transcript" in active_calls[call_sid]:
            return JSONResponse({
                "status": "success",
                "call_sid": call_sid,
                "transcript": active_calls[call_sid]["transcript"]
            })
        
        # Check if we have a transcript file for this call
        transcript_files = [f for f in os.listdir(transcripts_dir) if f.startswith(f"call_{call_sid}_")]
        
        if transcript_files:
            # Use the most recent transcript file
            transcript_files.sort(reverse=True)
            transcript_file = os.path.join(transcripts_dir, transcript_files[0])
            
            # Read the transcript file
            with open(transcript_file, 'r') as f:
                transcript_content = f.read()
            
            return JSONResponse({
                "status": "success",
                "call_sid": call_sid,
                "transcript_file": transcript_files[0],
                "transcript_content": transcript_content
            })
        
        return JSONResponse({
            "status": "error",
            "detail": f"No transcript found for call {call_sid}"
        }, status_code=404)
    except Exception as e:
        logger.error(f"Error fetching call transcript: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse({
            "status": "error",
            "detail": str(e)
        }, status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0") 