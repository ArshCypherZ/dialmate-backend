import json
import base64
import asyncio
import argparse
import os
import subprocess
import aiohttp
import websockets
import traceback

from contextlib import asynccontextmanager
from typing import Any, Dict
from pydantic import BaseModel

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.websockets import WebSocketDisconnect

from pipecat.transports.services.helpers.daily_rest import DailyRESTHelper, DailyRoomParams

from twilio.twiml.voice_response import Connect
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()



"""
RTVI Bot Server Implementation.

This FastAPI server manages RTVI bot instances and provides endpoints for both
direct browser access and RTVI client connections. It handles:
- Creating Daily rooms
- Managing bot processes
- Providing connection credentials
- Monitoring bot status
"""

# Data model for incoming request
class ConnectRequest(BaseModel):
    userId: str

# Constants
MAX_BOTS_PER_ROOM = 1

# Global state
bot_procs = {}
daily_helpers = {}


def cleanup():
    """Terminate all bot processes during server shutdown."""
    for proc, _ in bot_procs.values():
        proc.terminate()
        proc.wait()


def get_bot_file() -> str:
    """Return the bot file to execute."""
    return "bot-gemini"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    aiohttp_session = aiohttp.ClientSession()
    daily_helpers["rest"] = DailyRESTHelper(
        daily_api_key=os.getenv("DAILY_API_KEY"),
        daily_api_url="https://api.daily.co/v1",
        aiohttp_session=aiohttp_session,
    )
    yield
    await aiohttp_session.close()
    cleanup()


# Initialize FastAPI app
app = FastAPI(lifespan=lifespan)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def create_room_and_token() -> tuple[str, str]:
    """Create a Daily room and generate an access token."""
    room = await daily_helpers["rest"].create_room(DailyRoomParams())
    if not room.url:
        raise HTTPException(status_code=500, detail="Failed to create room")

    token = await daily_helpers["rest"].get_token(room.url)
    if not token:
        raise HTTPException(status_code=500, detail=f"Failed to get token for room: {room.url}")

    return room.url, token

user_id = None

@app.post("/getuser")
async def getuserId(request: Request):
    try:
        print("Request received at /getuser")
        data = await request.json()  # Parse JSON from request
        print(f"Request data: {data}")  # Log the data
        global user_id
        user_id = data.get("userId")
        return {"userId": user_id}
    except Exception as e:
        print(f"Error: {e}")  # Log the error
        raise HTTPException(status_code=500, detail="Internal Server Error")


@app.get("/")
async def start_agent(request: Request):
    global user_id
    """Create a room, start a bot, and redirect to the room URL."""
    print("Creating room...")
    room_url, token = await create_room_and_token()
    print(f"Room URL: {room_url}")

    # Check if max bots limit is reached
    if sum(1 for _, url in bot_procs.values() if url == room_url) >= MAX_BOTS_PER_ROOM:
        raise HTTPException(status_code=500, detail=f"Max bot limit reached for room: {room_url}")

    # Start bot process
    try:
        bot_file = get_bot_file()
        proc = subprocess.Popen(
            [f"python3 -m {bot_file} -u {room_url} -t {token} -user_id {user_id}"],
            shell=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        bot_procs[proc.pid] = (proc, room_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")

    return RedirectResponse(room_url)


@app.post("/connect")
async def rtvi_connect(request: Request) -> Dict[Any, Any]:
    global user_id
    """Create a room and return connection credentials."""
    print("Creating room for RTVI connection...")
    room_url, token = await create_room_and_token()
    print(f"Room URL: {room_url}")

    # Start bot process
    try:
        bot_file = get_bot_file()
        proc = subprocess.Popen(
            [f"python3 -m {bot_file} -u {room_url} -t {token} -user_id {user_id}"],
            shell=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        bot_procs[proc.pid] = (proc, room_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")

    return {"room_url": room_url, "token": token}


@app.get("/status/{pid}")
def get_status(pid: int):
    """Get the status of a specific bot process."""
    proc = bot_procs.get(pid)
    if not proc:
        raise HTTPException(status_code=404, detail=f"Bot with process ID: {pid} not found")

    status = "running" if proc[0].poll() is None else "finished"
    return JSONResponse({"bot_id": pid, "status": status})



"""
OpenAI Realtime Twilio Implementation.

This module implements a chatbot using OpenAI's realtime API into twilio.
It includes:
- Real-time audio interaction
- Speech-to-speech
- Can extract Transcription (check logs you will know how to)
- Connect with twilio (use POST to input your phone number twilio will call on that (only works for verified numbers from Arsh))

Steps to deploy:
pip install websockets fastapi twilio
ngrok http 7860
fill env
python3 server.py

Run:
curl -X POST https://<ngrokurl>/make-call -H "Content-Type: application/json" -d '{"to_phone_number": "+9111111"}'
"""



SYSTEM_MESSAGE = (
    "Your name is DialMate, You are a sales agent." # prompt
)
VOICE = "alloy" # check documentation for more voices
LOG_EVENT_TYPES = [
    "response.content.done",
    "rate_limits.updated",
    "response.done",
    "input_audio_buffer.committed",
    "input_audio_buffer.speech_stopped",
    "input_audio_buffer.speech_started",
    "session.created",
]
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
client = Client(account_sid, auth_token)

TWILIO_PHONE_NUMBER = os.getenv("TWILIO_FROM_NUMBER")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ngrokurl = os.getenv("NGROK_URL")


class CallRequest(BaseModel):
    to_phone_number: str

@app.post("/make-call")
async def make_call(request: CallRequest):
    """an outgoing call from Twilio."""
    to_phone_number = request.to_phone_number 
    
    try:
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Connecting you to the AI assistant.</Say>
    <Connect>
        <Stream name="arsh" url="wss://{ngrokurl}/media-stream" /> 
    </Connect>
    <Pause length="10" />
</Response>"""
        # paste here ^

        # Make the call
        call = client.calls.create(
            twiml=twiml,
            to=to_phone_number,
            from_=TWILIO_PHONE_NUMBER,
        )
        return {"message": "Call initiated.", "call_sid": call.sid}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connections between Twilio and OpenAI."""
    print("Client connected")
    await websocket.accept()

    async with websockets.connect(
        "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01",
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1",
        },
    ) as openai_ws:
        await send_session_update(openai_ws)
        await asyncio.gather(
            receive_from_twilio(websocket, openai_ws),
            send_to_twilio(websocket, openai_ws),
        )


async def send_session_update(openai_ws):
    """Sends session update details to OpenAI WebSocket."""
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "server_vad"},
            "input_audio_format": "g711_ulaw", # mu-law encoding for twilio
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": SYSTEM_MESSAGE,
            "modalities": ["text", "audio"],
            "temperature": 0.8,
        },
    }
    print("Sending session update:", json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))

current_stream_sid = None

async def receive_from_twilio(websocket: WebSocket, openai_ws):
    """Receive audio data from Twilio and forward it to OpenAI Realtime API."""
    global current_stream_sid
    try:
        async for message in websocket.iter_text():
            data = json.loads(message)
            if data["event"] == "media" and openai_ws.open:
                audio_append = {
                    "type": "input_audio_buffer.append",
                    "audio": data["media"]["payload"],
                }
                await openai_ws.send(json.dumps(audio_append))
            elif data["event"] == "start":
                current_stream_sid = data["start"]["streamSid"]
                print(f"Incoming stream started: {current_stream_sid}")
    except WebSocketDisconnect:
        print("Twilio client disconnected.")
        if openai_ws.open:
            await openai_ws.close()


async def send_to_twilio(websocket: WebSocket, openai_ws):
    global current_stream_sid
    """Receive audio responses from OpenAI and send them back to Twilio."""
    try:
        async for openai_message in openai_ws:
            response = json.loads(openai_message)
            if response["type"] in LOG_EVENT_TYPES:
                print(f"Received event: {response['type']}", response)
            elif response["type"] == "session.updated":
                print("Session updated:", response)
            elif response["type"] == "response.audio.delta" and response.get("delta"):
                try:
                    audio_payload = base64.b64encode(
                        base64.b64decode(response["delta"])
                    ).decode("utf-8")
                    print(response)
                    audio_delta = {
                        "event": "media",
                        "streamSid": current_stream_sid,
                        "media": {"payload": audio_payload},
                    }
                    print(current_stream_sid)
                    await websocket.send_json(audio_delta)
                except Exception as e:
                    print(f"Error processing audio data: {e}")
    except Exception as e:
        print(f"Error in sending data to Twilio: {e}")

@app.post("/error")
async def error():
    print("meow") # this is for twilio's error handling


if __name__ == "__main__":
    import uvicorn

    # Parse command-line arguments
    default_host = os.getenv("HOST", "0.0.0.0")
    default_port = int(os.getenv("FAST_API_PORT", "7860"))

    parser = argparse.ArgumentParser(description="Daily Storyteller FastAPI Server")
    parser.add_argument("--host", type=str, default=default_host, help="Host address")
    parser.add_argument("--port", type=int, default=default_port, help="Port number")
    parser.add_argument("--reload", action="store_true", help="Reload code on changes")

    config = parser.parse_args()

    # Run the FastAPI server
    uvicorn.run(
        "server:app",
        host=config.host,
        port=config.port,
        reload=config.reload,
    )
