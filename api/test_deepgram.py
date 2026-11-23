import asyncio
import os
from dotenv import load_dotenv
from livekit.plugins import deepgram

load_dotenv("api/.env")


async def main():
    stt = deepgram.STT(model="nova-3", language="en")

    print("Deepgram STT initialized successfully!")


asyncio.run(main())
