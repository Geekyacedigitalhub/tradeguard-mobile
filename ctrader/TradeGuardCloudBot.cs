using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using cAlgo.API;

namespace cAlgo.Robots;

[Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
public class TradeGuardCloudBot : Robot
{
    [Parameter("API Base URL", Group = "TradeGuard", DefaultValue = "https://tradeguard-api.fastapicloud.dev")]
    public string ApiBaseUrl { get; set; }

    [Parameter("User ID", Group = "TradeGuard", DefaultValue = "")]
    public string UserId { get; set; }

    [Parameter("Runtime Token", Group = "TradeGuard", DefaultValue = "")]
    public string RuntimeToken { get; set; }

    [Parameter("Heartbeat Seconds", Group = "TradeGuard", DefaultValue = 10, MinValue = 5)]
    public int HeartbeatSeconds { get; set; }

    [Parameter("Command Poll Seconds", Group = "TradeGuard", DefaultValue = 3, MinValue = 1)]
    public int CommandPollSeconds { get; set; }

    private DateTime _lastHeartbeat = DateTime.MinValue;
    private DateTime _lastCommandPoll = DateTime.MinValue;

    protected override void OnStart()
    {
        if (string.IsNullOrWhiteSpace(ApiBaseUrl) || string.IsNullOrWhiteSpace(UserId) || string.IsNullOrWhiteSpace(RuntimeToken))
        {
            Print("TradeGuard cTrader: missing API URL, User ID, or Runtime Token.");
            Stop();
            return;
        }

        Timer.Start(1);
        Print("TradeGuard cTrader Cloud initialized.");
        Heartbeat();
    }

    protected override void OnTimer()
    {
        var now = Server.Time;

        if ((now - _lastHeartbeat).TotalSeconds >= HeartbeatSeconds)
            Heartbeat();

        if ((now - _lastCommandPoll).TotalSeconds >= CommandPollSeconds)
            PollCommands();
    }

    private void Heartbeat()
    {
        _lastHeartbeat = Server.Time;
        var positions = Positions.Select(p => new
        {
            id = p.Id,
            symbol = p.SymbolName,
            side = p.TradeType == TradeType.Buy ? "BUY" : "SELL",
            volume = p.VolumeInUnits,
            entry = p.EntryPrice,
            current_price = p.CurrentPrice,
            stop_loss = p.StopLoss,
            take_profit = p.TakeProfit,
            pnl = p.NetProfit
        }).ToArray();

        var body = JsonSerializer.Serialize(new
        {
            user_id = UserId,
            account = Account.Number.ToString(),
            environment = "demo",
            terminal = "cTrader Cloud",
            connected = true,
            balance = Account.Balance,
            equity = Account.Equity,
            today_pl = 0.0,
            positions
        });

        var request = NewRequest("/v1/ctrader/heartbeat", "POST", body);
        var response = Http.Send(request);
        if (!response.IsSuccessful)
            Print("TradeGuard heartbeat failed: {0}", response.StatusCode);
    }

    private void PollCommands()
    {
        _lastCommandPoll = Server.Time;
        var url = $"{ApiBaseUrl.TrimEnd('/')}/v1/ctrader/commands?limit=3&user_id={Uri.EscapeDataString(UserId)}";
        var request = NewRequest(url, "GET", null);
        var response = Http.Send(request);
        if (!response.IsSuccessful)
        {
            Print("TradeGuard command poll failed: {0}", response.StatusCode);
            return;
        }

        using var document = JsonDocument.Parse(response.Body);
        if (!document.RootElement.TryGetProperty("commands", out var commands))
            return;

        foreach (var command in commands.EnumerateArray())
        {
            var id = command.GetProperty("id").GetInt64();
            var type = command.GetProperty("type").GetString() ?? "";
            var payload = command.GetProperty("payload");
            try
            {
                var result = type switch
                {
                    "open_market" => OpenMarket(payload),
                    "close_position" => ClosePosition(payload),
                    _ => new { ok = false, error = $"Unsupported command: {type}" }
                };
                SendResult(id, "completed", result);
            }
            catch (Exception ex)
            {
                SendResult(id, "failed", new { ok = false, error = ex.Message });
            }
        }
    }

    private object OpenMarket(JsonElement payload)
    {
        var symbolName = payload.GetProperty("symbol").GetString() ?? SymbolName;
        var symbol = Symbols.GetSymbol(symbolName);
        if (symbol == null)
            throw new Exception($"Symbol not found: {symbolName}");

        var side = payload.GetProperty("side").GetString();
        var tradeType = side == "BUY" ? TradeType.Buy : side == "SELL" ? TradeType.Sell : throw new Exception("Invalid side");

        var stop = payload.GetProperty("stop_loss").GetDouble();
        var target = payload.GetProperty("take_profit").GetDouble();
        var riskAmount = payload.TryGetProperty("risk_amount", out var riskNode) ? riskNode.GetDouble() : Account.Balance * 0.005;
        var entry = tradeType == TradeType.Buy ? symbol.Ask : symbol.Bid;
        var stopPips = Math.Abs(entry - stop) / symbol.PipSize;
        if (stopPips <= 0)
            throw new Exception("Invalid stop distance");

        var volume = symbol.VolumeForFixedRisk(riskAmount, stopPips, RoundingMode.Down);
        volume = symbol.NormalizeVolumeInUnits(volume, RoundingMode.Down);
        if (volume < symbol.VolumeInUnitsMin)
            throw new Exception($"Minimum broker volume would exceed the requested risk on {symbolName}");

        var result = ExecuteMarketOrder(tradeType, symbolName, volume, "TradeGuard", stopPips, Math.Abs(target - entry) / symbol.PipSize);
        if (!result.IsSuccessful || result.Position == null)
            throw new Exception(result.Error?.ToString() ?? "cTrader order failed");

        var position = result.Position;
        return new
        {
            ok = true,
            position = new
            {
                id = position.Id,
                symbol = position.SymbolName,
                side = position.TradeType == TradeType.Buy ? "BUY" : "SELL",
                entry = position.EntryPrice,
                volume = position.VolumeInUnits,
                stop_loss = position.StopLoss,
                take_profit = position.TakeProfit
            }
        };
    }

    private object ClosePosition(JsonElement payload)
    {
        var ticket = payload.GetProperty("ticket").GetInt64();
        var position = Positions.FirstOrDefault(p => p.Id == ticket);
        if (position == null)
            throw new Exception($"Position {ticket} not found");

        var result = ClosePosition(position);
        if (!result.IsSuccessful)
            throw new Exception(result.Error?.ToString() ?? "cTrader close failed");

        return new
        {
            ok = true,
            position = new
            {
                id = position.Id,
                symbol = position.SymbolName,
                exit_price = position.CurrentPrice,
                pnl = position.NetProfit
            }
        };
    }

    private HttpRequest NewRequest(string pathOrUrl, string method, string body)
    {
        var url = pathOrUrl.StartsWith("http", StringComparison.OrdinalIgnoreCase)
            ? pathOrUrl
            : $"{ApiBaseUrl.TrimEnd('/')}{pathOrUrl}";

        var request = new HttpRequest(new Uri(url));
        request.Method = method == "POST" ? HttpMethod.Post : HttpMethod.Get;
        request.Headers.Add("X-Bridge-Token", RuntimeToken);
        request.Headers.Add("Content-Type", "application/json");
        if (body != null)
            request.Body = body;
        return request;
    }

    private void SendResult(long commandId, string status, object result)
    {
        var body = JsonSerializer.Serialize(new
        {
            command_id = commandId,
            status,
            result
        });
        var request = NewRequest($"/v1/ctrader/commands/result?user_id={Uri.EscapeDataString(UserId)}", "POST", body);
        var response = Http.Send(request);
        if (!response.IsSuccessful)
            Print("TradeGuard result failed: {0}", response.StatusCode);
    }
}
