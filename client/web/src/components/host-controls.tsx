"use client";

import MicToggle from "@/components/controls/mic-toggle";
import LeaveButton from "@/components/controls/leave-button";
import CaptionsToggle from "@/components/controls/captions-toggle";
import CaptionsLanguageSelect from "@/components/controls/captions-language-select";
import DeviceSelector from "@/components/controls/device-selector";

export default function HostControls() {
  return (
    <div className="flex items-center justify-center gap-4">
      <DeviceSelector />
      <MicToggle />
      <CaptionsToggle />
      <CaptionsLanguageSelect />
      <LeaveButton />
    </div>
  );
}
