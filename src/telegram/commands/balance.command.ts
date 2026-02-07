import { Context } from 'telegraf';
import { BalanceService } from '../../services/balance.service';
import { TradeService } from '../../services/trade.service';
import { BinanceService } from '../../services/binance.service';

export class BalanceCommand {
  constructor(
    private balanceService: BalanceService,
    private tradeService: TradeService,
    private binanceService: BinanceService
  ) {}

  async execute(ctx: Context, args: string[]): Promise<void> {
    const userId = ctx.from?.id;
    if (!userId) {
      await ctx.reply('Unable to identify user');
      return;
    }

    try {
      const totalBalance = await this.balanceService.getBalance(userId);
      const realizedBalance = await this.balanceService.getRealizedBalance(userId);
      const unrealizedPnL = totalBalance - realizedBalance;

      const openTrades = await this.tradeService.getOpenTrades(userId);
      
      let message = `💰 *Balance Overview*\n\n`;
      message += `Total Balance: *${totalBalance.toFixed(2)} USDT*\n`;
      message += `Realized P&L: ${realizedBalance >= 0 ? '✅' : '❌'} ${realizedBalance.toFixed(2)} USDT\n`;
      message += `Unrealized P&L: ${unrealizedPnL >= 0 ? '📈' : '📉'} ${unrealizedPnL.toFixed(2)} USDT\n`;
      
      if (openTrades.length > 0) {
        message += `\n📊 *Open Positions: ${openTrades.length}*\n`;
        for (const trade of openTrades) {
          const currentPrice = await this.binanceService.getCurrentPrice(trade.symbol);
          const pnl = await this.tradeService.calculateProfit(trade, currentPrice);
          const pnlPercent = (pnl / (parseFloat(trade.entryPrice) * parseFloat(trade.quantity))) * 100;
          
          message += `\n${trade.symbol} ${trade.side}\n`;
          message += `Entry: ${parseFloat(trade.entryPrice).toFixed(4)} | Current: ${currentPrice.toFixed(4)}\n`;
          message += `P&L: ${pnl >= 0 ? '✅' : '❌'} ${pnl.toFixed(2)} USDT (${pnlPercent.toFixed(2)}%)\n`;
        }
      }

      await ctx.reply(message, { parse_mode: 'Markdown' });
    } catch (error) {
      console.error('Balance command error:', error);
      await ctx.reply('Failed to retrieve balance information');
    }
  }
}