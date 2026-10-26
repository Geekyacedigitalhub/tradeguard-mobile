import {useEffect, useRef} from "react";
import {api} from "./api";

export type LiveTick = {symbol: string; price: number; time: number};

// Subscribe to the broker market stream for ALL symbols and forward validated
// ticks to the callback. Returns nothing; unmount cleans up the socket.
export function useLiveTicks(onTick: (tick: LiveTick) => void): void {
  const cbRef = useRef(onTick);
  cbRef.current = onTick;

  useEffect(() => {
    let cleanup: (() => void) | null = null;
    let cancelled = false;
    const subscribe = async () => {
      const un = await api.marketStream(
        (t: any) => {
          const price = Number(t?.price);
          if (t?.type === "tick" && Number.isFinite(price) && price > 0) {
            cbRef.current({symbol: String(t.symbol ?? "").toUpperCase(), price, time: Date.now()});
          }
        },
        undefined,
        "" // empty symbol = receive every tick
      );
      if (cancelled) un();
      else cleanup = un;
    };
    void subscribe();
    return () => {
      cancelled = true;
      if (cleanup) cleanup();
    };
  }, []);
}
