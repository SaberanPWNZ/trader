import { UserRepository } from '../repositories/UserRepository';
import { TradeRepository } from '../repositories/TradeRepository';
import { TradeService } from './TradeService';

export class BalanceService {
  private userRepository: UserRepository;
  private tradeRepository: TradeRepository;
  private tradeService: TradeService;

  constructor(
    userRepository: UserRepository,
    tradeRepository: TradeRepository,
    tradeService: TradeService
  ) {
    this.userRepository = userRepository;
    this.tradeRepository = tradeRepository;
    this.tradeService = tradeService;
  }

  async getBalance(userId: number): Promise<number> {
    const user = await this.userRepository.findOne({ where: { id: userId } });
    if (!user) {
      throw new Error('User not found');
    }

    const closedTrades = await this.tradeRepository.find({
      where: { userId, status: 'CLOSED' }
    });

    let totalProfit = 0;
    for (const trade of closedTrades) {
      if (trade.profit) {
        totalProfit += parseFloat(trade.profit);
      }
    }

    const unrealizedPnL = await this.tradeService.getUnrealizedPnL(userId);
    
    return parseFloat(user.balance) + totalProfit + unrealizedPnL;
  }

  async getRealizedBalance(userId: number): Promise<number> {
    const user = await this.userRepository.findOne({ where: { id: userId } });
    if (!user) {
      throw new Error('User not found');
    }

    const closedTrades = await this.tradeRepository.find({
      where: { userId, status: 'CLOSED' }
    });

    let totalProfit = 0;
    for (const trade of closedTrades) {
      if (trade.profit) {
        totalProfit += parseFloat(trade.profit);
      }
    }

    return parseFloat(user.balance) + totalProfit;
  }
}