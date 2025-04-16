import CaptionsToggle from "@/components/controls/captions-toggle";
import CaptionsLanguageSelect from "@/components/controls/captions-language-select";
import LeaveButton from "@/components/controls/leave-button";

export default function ListenerControls() {
  return (
    <div className="flex items-center justify-center gap-4">
      <CaptionsToggle />
      <CaptionsLanguageSelect />
      <LeaveButton />
    </div>
  );
}
