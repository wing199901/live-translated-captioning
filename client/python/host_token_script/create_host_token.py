from livekit import api
import asyncio


async def main():

    token = (
        api.AccessToken()
        .with_identity("test2")
        .with_name("test2")
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room="my-room",
            )
        )
        .with_attributes(
            attributes={
                "user_type": "host",
            }
        )
        .to_jwt()
    )

    print(token)

    lkapi = api.LiveKitAPI()
    room_info = await lkapi.room.create_room(
        api.CreateRoomRequest(name="my-room"),
    )
    print(room_info)
    room_list = await lkapi.room.list_rooms(api.ListRoomsRequest())
    print(room_list)
    await lkapi.aclose()


if __name__ == "__main__":
    asyncio.run(main())
