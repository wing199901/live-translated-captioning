import asyncio
import logging
from typing import Dict

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobRequest,
    WorkerOptions,
    cli,
    stt,
    transcription,
)
from livekit.plugins import openai, silero, deepgram

load_dotenv()

logger = logging.getLogger("transcriber")


class ParticipantState:
    def __init__(self):
        self._forward_transcription = True
        self._transcription_language = "english"
        self._lock = asyncio.Lock()

    async def set_participant_state(self, should_forward: bool, language: str):
        async with self._lock:
            self._forward_transcription = should_forward
            self._transcription_language = language
            logger.info(f"State updated: forward={should_forward}")

    async def set_forward_transcription(self, should_forward: bool):
        async with self._lock:
            self._forward_transcription = should_forward
            logger.info(f"State updated: forward={should_forward}")

    async def get_should_forward_transcription(self):
        async with self._lock:
            return self._forward_transcription

    async def get_transcription_language(self):
        async with self._lock:
            return self._transcription_language


class ParticipantManager:
    def __init__(self):
        self._states: Dict[str, ParticipantState] = {}
        self._lock = asyncio.Lock()

    async def get_state(self, key: str) -> ParticipantState:
        async with self._lock:
            if key not in self._states:
                self._states[key] = ParticipantState()
                logger.info(f"Created new state for participant: {key}")
            return self._states[key]

    async def set_transcription_forward_value(
        self, key: str, should_forward_transcription: bool, transcription_language: str
    ):
        state = await self.get_state(key)
        await state.set_forward_transcription(should_forward_transcription)

    async def set_participant_state(
        self, key: str, should_forward_transcription: bool, transcription_language: str
    ):
        state = await self.get_state(key)
        await state.set_participant_state(
            should_forward_transcription, transcription_language
        )

    async def get_transcription_forward_value(self, key: str) -> bool:
        state = await self.get_state(key)
        return await state.get_should_forward_transcription()

    async def remove_participant_state(self, key: str):
        async with self._lock:
            if key in self._states:
                del self._states[key]
                logger.info(f"Removed state for participant: {key}")
                return True
            logger.warning(f"Tried to remove non-existent state for participant: {key}")
            return False

    async def loop_states(self):
        async with self._lock:
            for key, state in self._states.items():
                yield key, state

    async def language_exists(self, language: str) -> bool:
        async with self._lock:
            for state in self._states.values():
                if await state.get_transcription_language() == language:
                    return True
            return False


participant_manager = ParticipantManager()


async def forward_transcription(
    stt_stream: stt.SpeechStream,
    stt_forwarder: transcription.STTSegmentsForwarder,
    language: str,
):
    """Forward transcription to clients and log the transcript."""
    async for ev in stt_stream:
        if ev.type == stt.SpeechEventType.FINAL_TRANSCRIPT:
            async for key, state in participant_manager.loop_states():
                if await state.get_should_forward_transcription():
                    logger.info(
                        f"Transcription for participant {key} (lang: {language}): {ev.alternatives[0].text}"
                    )
                    # Send data message
                else:
                    logger.info(f"Ignoring transcription for participant: {key}")
        stt_forwarder.update(ev)


def str_to_bool(string: str) -> bool:
    return string.lower() == "true"


async def entrypoint(ctx: JobContext):
    logger.info(f"Starting transcriber (STT) for room: {ctx.room.name}")
    stt = deepgram.STT()
    stt_stream = stt.stream()

    # stt_impl = openai.STT()

    # if not stt_impl.capabilities.streaming:
    #     stt_impl = stt.StreamAdapter(
    #         stt=stt_impl,
    #         vad=silero.VAD.load(min_silence_duration=0.2),
    #     )

    stt_forwarder = None

    async def add_participant_to_state(participant: rtc.RemoteParticipant):
        try:
            transcription_language = participant.attributes["transcription_language"]
            should_forward = str_to_bool(
                participant.attributes["should_forward_transcription"]
            )

            if not await participant_manager.language_exists(transcription_language):
                logger.info(
                    f"Adding transcription task for language: {transcription_language}"
                )
                asyncio.create_task(
                    forward_transcription(
                        stt_stream, stt_forwarder, transcription_language
                    )
                )

            await participant_manager.set_participant_state(
                participant.identity, should_forward, transcription_language
            )
        except Exception as e:
            logger.error(
                f"Error adding participant {participant.identity} to state: {e}",
                exc_info=True,
            )

    async def transcribe_track(participant: rtc.RemoteParticipant, track: rtc.Track):
        nonlocal stt_forwarder, stt_stream
        try:
            audio_stream = rtc.AudioStream(track)
            stt_forwarder = transcription.STTSegmentsForwarder(
                room=ctx.room, participant=participant, track=track
            )
            # stt_stream = stt_impl.stream()

            async for ev in audio_stream:
                stt_stream.push_frame(ev.frame)
        except Exception as e:
            logger.error(
                f"Error transcribing track for participant {participant.identity}: {e}",
                exc_info=True,
            )

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    @ctx.room.on("participant_connected")
    def on_participant_connected(participant: rtc.RemoteParticipant) -> None:
        attributes = participant.attributes
        if attributes["user_type"] == "listener":
            logger.info(f"Participant added to state: {participant.identity}")
            asyncio.create_task(add_participant_to_state(participant))

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.TrackPublication,
        participant: rtc.RemoteParticipant,
    ):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            attributes = participant.attributes
            if attributes["user_type"] == "host":
                logger.info(f"Track subscribed for participant: {participant.identity}")
                asyncio.create_task(transcribe_track(participant, track))

    @ctx.room.on("participant_disconnected")
    async def on_participant_disconnected(participant: rtc.RemoteParticipant):
        await participant_manager.remove_participant_state(participant.identity)

    @ctx.room.local_participant.register_rpc_method("toggle_transcription")
    async def handle_toggle_transcription(data: rtc.RpcInvocationData):
        should_forward = str_to_bool(data.payload)
        await participant_manager.set_transcription_forward_value(
            data.caller_identity, should_forward
        )
        logger.info(
            f"Toggle transcription for {data.caller_identity}: {should_forward}"
        )


async def request_fnc(req: JobRequest):
    await req.accept(identity="agent")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint, agent_name="test-agent", request_fnc=request_fnc
        )
    )
