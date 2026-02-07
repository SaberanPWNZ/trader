ghjcrfyeq ghjtrnimport { Injectable } from '@nestjs/common';
import { Trade } from '../entities/trade.entity';
import { BinanceService } from './BinanceService';

@Injectable()
export class TradeService {
  constructor(
    private readonly binanceService: BinanceService,
    // ...other dependencies
  ) {}

  async calculateProfit(trade: Trade, currentPrice: number): Promise<number> {
    const quantity = parseFloat(trade.quantity);
    const entryPrice = parseFloat(trade.entryPrice);
    
    if (trade.side === 'LONG') {
      return (currentPrice - entryPrice) * quantity;
    } else {
      return (entryPrice - currentPrice) * quantity;
    }
  }

  async getUnrealizedPnL(userId: number): Promise<number> {
    const openTrades = await this.tradeRepository.find({
      where: { userId, status: 'OPEN' }
    });

    let totalPnL = 0;
    for (const trade of openTrades) {
      const currentPrice = await this.binanceService.getCurrentPrice(trade.symbol);
      const pnl = await this.calculateProfit(trade, currentPrice);
      totalPnL += pnl;
    }

    return totalPnL;
  }

  // ...existing methods
}