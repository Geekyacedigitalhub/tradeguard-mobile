import {DeviceEventEmitter} from "react-native";

export const CTRADER_ACCOUNT_CHANGED = "tradeguard:ctrader-account-changed";

export type CTraderAccountIdentity = {
  account_id?: string | number | null;
  environment?: string | null;
};

export function emitCTraderAccountChanged(identity: CTraderAccountIdentity) {
  DeviceEventEmitter.emit(CTRADER_ACCOUNT_CHANGED, identity);
}

export function onCTraderAccountChanged(listener: (identity: CTraderAccountIdentity) => void) {
  const subscription = DeviceEventEmitter.addListener(CTRADER_ACCOUNT_CHANGED, listener);
  return () => subscription.remove();
}
