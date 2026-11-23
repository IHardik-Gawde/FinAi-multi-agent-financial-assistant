from dotenv import load_dotenv
from livekit.plugins import elevenlabs

load_dotenv("api/.env")

tts = elevenlabs.TTS()

print("ElevenLabs TTS initialized successfully!")
