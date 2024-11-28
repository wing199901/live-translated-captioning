import asyncio
import logging
from signal import SIGINT, SIGTERM
import time
from typing import Union
import os

from livekit import api, rtc

# ensure LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET are set


async def main(room: rtc.Room) -> None:
    @room.on("data_received")
    def on_data_received(data: rtc.DataPacket):
        logging.info(
            "received data from %s: %s",
            data.participant.identity,
            data.data.decode("utf-8"),
        )

    token = (
        api.AccessToken()
        .with_identity("python-bot-3")
        .with_name("Python Bot 3")
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room="my-room",
            )
        )
        .with_attributes(
            attributes={
                "should_forward_transcription": "true",
                "transcription_language": "french",
                "user_type": "listener",
            }
        )
        .to_jwt()
    )
    await room.connect(os.getenv("LIVEKIT_URL"), token)
    logging.info("connected to room %s", room.name)
    logging.info("participants: %s", room.remote_participants)

    await asyncio.sleep(2)
    await room.local_participant.publish_data("hello world")

    # try:
    #     response = await room.local_participant.perform_rpc(
    #         destination_identity="agent",
    #         method="toggle_transcription",
    #         payload="false",
    #     )
    #     print(f"RPC response: {response}")
    # except Exception as e:
    #     print(f"RPC call failed: {e}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        handlers=[logging.FileHandler("basic_room.log"), logging.StreamHandler()],
    )

    loop = asyncio.get_event_loop()
    room = rtc.Room(loop=loop)

    async def cleanup():
        await room.disconnect()
        loop.stop()

    asyncio.ensure_future(main(room))
    for signal in [SIGINT, SIGTERM]:
        loop.add_signal_handler(signal, lambda: asyncio.ensure_future(cleanup()))

    try:
        loop.run_forever()
    finally:
        loop.close()
