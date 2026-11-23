import asyncio
from dotenv import load_dotenv
from livekit import api

load_dotenv("api/.env")


async def main():
    async with api.LiveKitAPI() as lkapi:
        result = await lkapi.room.list_rooms(api.ListRoomsRequest())
        print("LiveKit authentication successful!")
        print("Active rooms:", len(result.rooms))


asyncio.run(main())
