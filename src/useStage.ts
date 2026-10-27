import { useEffect } from "react";
import { jstage } from "./crashjournal";

// Records "screen:<name>" (and "screen_<name>_unmounted") in the crash journal
// when the screen mounts/unmounts. Tells us exactly how far the UI got.
export function useStage(name: string) {
  useEffect(() => {
    jstage("screen_mount", { screen: name });
    return () => {
      jstage("screen_unmount", { screen: name });
    };
  }, [name]);
}
