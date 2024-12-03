"use client";

import { useRouter } from "next/navigation";
import { useRoomContext } from "@livekit/components-react";
import { Button } from "@/components/ui/button";
import { Mic, MicOff, X } from "react-feather";

export default function HostControls() {
  const room = useRoomContext();
  const router = useRouter();

  const onClose = async () => {
    await room.disconnect();
    router.push("/");
  };

  return (
    <div className="flex items-center justify-center gap-4">
      <Button
        variant="outline"
        className="h-[64px] w-[64px] rounded-full"
        onClick={(e) => {
          room.localParticipant.setMicrophoneEnabled(
            !room.localParticipant.isMicrophoneEnabled
          );
        }}
      >
        {room.localParticipant.isMicrophoneEnabled ? (
          <Mic style={{ width: "24px", height: "24px" }} />
        ) : (
          <MicOff style={{ width: "24px", height: "24px" }} />
        )}
      </Button>
      <div
        className="w-[64px] h-[64px] rounded-full bg-red-600 flex items-center justify-center"
        onClick={onClose}
      >
        <X size={32} className="text-white" />
      </div>
    </div>
  );
}
