import { useRoomContext } from "@livekit/components-react";
import { BiCaptions, BiSolidCaptions } from "react-icons/bi";
import { usePartyState } from "@/hooks/usePartyState";
import LanguageSelect from "@/components/language-select";
import { Button } from "@/components/ui/button";

export default function ListenerControls() {
  const room = useRoomContext();
  const { state, dispatch } = usePartyState();

  return (
    <div className="flex items-center justify-center gap-4">
      <Button
        variant="outline"
        className=" flex items-center justify-center"
        onClick={(e) => {
          dispatch({
            type: "SET_CAPTIONS_ENABLED",
            payload: !state.captionsEnabled,
          });
        }}
      >
        {state.captionsEnabled ? (
          <BiSolidCaptions style={{ width: "24px", height: "24px" }} />
        ) : (
          <BiCaptions style={{ width: "24px", height: "24px" }} />
        )}
      </Button>
      <LanguageSelect disabled={!state.captionsEnabled} />
    </div>
  );
}
