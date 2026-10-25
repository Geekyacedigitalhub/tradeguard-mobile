import React from "react";
import renderer, { act } from "react-test-renderer";

import Bot from "../app/(tabs)/bot";
import { api } from "../src/api";

jest.mock("../src/api", () => {
  const actual = jest.requireActual("../src/api");
  return {
    ...actual,
    api: {
      bot: jest.fn(),
      aiApproval: jest.fn(),
      ctraderAccount: jest.fn(),
      account: jest.fn(),
      journalStats: jest.fn(),
      notificationEvents: jest.fn(),
      startBot: jest.fn(),
      stopBot: jest.fn(),
      updateMode: jest.fn(),
      updateAiApproval: jest.fn(),
      updateRisk: jest.fn(),
      emergencyStop: jest.fn(),
      closeAll: jest.fn(),
      cTraderCommand: jest.fn(),
    },
  };
});

const mockedApi = api as jest.Mocked<typeof api>;

/** Collect visible text so assertions read like the rendered screen. */
function textOf(tree: renderer.ReactTestRenderer): string {
  return tree.root
    // React Native host text nodes carry the "Text" type tag at runtime.
    .findAll(node => (node.type as unknown as string) === "Text")
    .map(node => node.children.filter((child): child is string => typeof child === "string").join(""))
    .join(" | ");
}

const engine = {
  running: true,
  emergency_stopped: false,
  mode: "semi_auto",
  risk_per_trade: 0.5,
  daily_loss_limit: 2,
  max_open_trades: 3,
  max_drawdown: 5,
};

const brokerSnapshot = {
  connected: true,
  account_id: 1234567,
  environment: "demo",
  currency: "USD",
  balance: 10000,
  equity: 10042.5,
  unrealized_pnl: 42.5,
  today_pl: -35.25,
  drawdown: 1.4,
  positions_count: 1,
  updated_at: new Date().toISOString(),
};

async function renderBot() {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {
    tree = renderer.create(<Bot />);
  });
  await act(async () => { await Promise.resolve(); });
  return tree;
}

beforeEach(() => {
  jest.clearAllMocks();
  mockedApi.bot.mockResolvedValue(engine as any);
  mockedApi.aiApproval.mockResolvedValue({ enabled: true, min_score: 82 } as any);
  mockedApi.ctraderAccount.mockResolvedValue(brokerSnapshot as any);
  mockedApi.account.mockResolvedValue({ balance: 10000, equity: 10042.5, today_pl: -35.25, drawdown: 1.4, currency: "USD" } as any);
  mockedApi.journalStats.mockResolvedValue({ entries: 4, wins: 3, losses: 1, win_rate: 75, total_pnl: 210.5, total_r: 2.4 } as any);
  mockedApi.notificationEvents.mockResolvedValue({
    events: [
      { id: 2, type: "notification_signal", payload: { symbol: "EURUSD", action: "BUY", score: 84 }, created_at: new Date().toISOString() },
      { id: 1, type: "notification_trade_execution_blocked", payload: { symbol: "XAUUSD", reason: "Sizing not verified" }, created_at: new Date().toISOString() },
    ],
  } as any);
});

test("renders live broker metrics and engine state", async () => {
  const tree = await renderBot();
  const text = textOf(tree);

  expect(text).toContain("Bot Console");
  expect(text).toContain("MONITORING");
  expect(text).toContain("SEMI-AUTO");
  // Broker figures come through unchanged, never reformatted into fake values.
  expect(text).toContain("10,042.50 USD");
  expect(text).toContain("10,000.00 USD");
  expect(text).toContain("-35.25 USD");
  expect(text).toContain("75.0%");
  expect(text).toContain("+2.40R");
  // The routing lock must always be visible while sizing is unverified.
  expect(text).toContain("ORDER ROUTING LOCKED");
  // Risk gauges are derived, not hard-coded.
  expect(text).toContain("33.3% of limit");
  expect(text).toContain("28.0% of limit");
  expect(text).toContain("17.6% of limit");
  tree.unmount();
});

test("shows the execution feed with event text", async () => {
  const tree = await renderBot();
  const text = textOf(tree);
  expect(text).toContain("SIGNAL");
  expect(text).toContain("EURUSD");
  expect(text).toContain("ENTRY BLOCKED");
  tree.unmount();
});

test("falls back to an offline console when the engine cannot be read", async () => {
  mockedApi.bot.mockRejectedValue(new Error("backend unreachable"));
  const tree = await renderBot();
  const text = textOf(tree);
  expect(text).toContain("ENGINE STATUS UNAVAILABLE");
  expect(text).toContain("EMERGENCY STOP");
  tree.unmount();
});

test("withholds broker figures when no account is selected", async () => {
  const notSelected = Object.assign(new Error("Select a cTrader account"), { status: 409 });
  mockedApi.ctraderAccount.mockRejectedValue(notSelected);
  mockedApi.account.mockRejectedValue(notSelected);
  const tree = await renderBot();
  const text = textOf(tree);
  expect(text).toContain("No broker account selected");
  expect(text).not.toContain("10,042.50");
  tree.unmount();
});

test("renders the emergency latch state without claiming trading is active", async () => {
  mockedApi.bot.mockResolvedValue({ ...engine, running: false, emergency_stopped: true } as any);
  const tree = await renderBot();
  const text = textOf(tree);
  expect(text).toContain("HALTED");
  expect(text).toContain("Emergency latch active");
  // START is rejected by the backend while latched, so the dock must offer reset.
  expect(text).toContain("RESET LATCH");
  expect(text).not.toContain("START BOT");
  expect(text).not.toContain("Scanning markets for qualifying setups");
  tree.unmount();
});

test("withholds stale broker figures instead of showing them as current", async () => {
  mockedApi.ctraderAccount.mockResolvedValue({
    ...brokerSnapshot,
    updated_at: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
  } as any);
  const tree = await renderBot();
  const text = textOf(tree);
  expect(text).toContain("SNAPSHOT STALE");
  expect(text).not.toContain("10,042.50 USD");
  expect(text).toContain("Broker snapshot is older than 45 seconds");
  tree.unmount();
});
