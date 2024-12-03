import React, { useState } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useRoomContext } from "@livekit/components-react";
import { usePartyState } from "@/hooks/usePartyState";

interface Language {
  code: string;
  name: string;
  flag: string;
}

interface LanguageSelectProps {
  disabled: boolean;
}

const LanguageSelect = ({ disabled = false }: LanguageSelectProps) => {
  const room = useRoomContext();
  const { state, dispatch } = usePartyState();

  const languages: Language[] = [
    { code: "en", name: "American English", flag: "🇺🇸" },
    { code: "es", name: "Spanish", flag: "🇪🇸" },
    { code: "fr", name: "French", flag: "🇫🇷" },
    { code: "de", name: "German", flag: "🇩🇪" },
    { code: "ja", name: "Japanese", flag: "🇯🇵" },
  ];

  const handleChange = async (value: string) => {
    dispatch({
      type: "SET_CAPTIONS_LANGUAGE",
      payload: value,
    });
    await room.localParticipant.setAttributes({
      captions_language: value,
    });
  };

  return (
    <div className="flex items-center">
      <Select
        value={state.captionsLanguage}
        onValueChange={handleChange}
        disabled={disabled}
      >
        <SelectTrigger className="w-[180px]">
          <SelectValue placeholder="Theme" />
        </SelectTrigger>
        <SelectContent>
          {languages.map((lang) => (
            <SelectItem key={lang.code} value={lang.code}>
              {lang.flag} {lang.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
};

export default LanguageSelect;
