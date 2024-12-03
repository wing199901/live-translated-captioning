"use client";

import MicToggle from "@/components/controls/mic-toggle";
import LeaveButton from "@/components/controls/leave-button";
import CaptionsToggle from "@/components/controls/captions-toggle";
import LanguageSelect from "@/components/controls/language-select";

export default function HostControls() {
  return (
    <div className="flex items-center justify-center gap-4">
      <MicToggle />
      <CaptionsToggle />
      <LanguageSelect />
      <LeaveButton />
    </div>
  );
}
