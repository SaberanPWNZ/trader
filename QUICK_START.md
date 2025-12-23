# Crypto AI Trading Bot - Quick Start

## 🚀 Single Command to Run Everything

### Варіант 1: Використовувати `make`

```bash
make run
```

Це стартує всі сервіси (scheduler + telegram bot + trading bot).

### Варіант 2: Використовувати shell script

```bash
./start.sh
```

---

## 📋 Доступні Make команди

```bash
make run              # Запустити все (scheduler, telegram bot, trading)
make build            # Збудувати Docker image
make stop             # Зупинити все
make restart          # Перезапустити все
make logs             # Логи основного bot-а
make logs-scheduler   # Логи scheduler
make logs-bot         # Логи telegram bot
make logs-all         # Логи всього
make train SYMBOL=BTC # Ручне тренування моделі
make clean            # Видалити контейнери та дані
```

---

## 🔧 Перед першим запуском

1. **Встановіть environment variables:**

```bash
export BINANCE_API_KEY=your_key_here
export BINANCE_API_SECRET=your_secret_here
export TELEGRAM_BOT_TOKEN=your_token_here
export TELEGRAM_CHAT_ID=your_chat_id_here
```

Або створіть `.env` файл:

```bash
cat > .env << EOF
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
EOF
```

2. **Запустіть все:**

```bash
make run
```

---

## 📊 Що запускається

| Сервіс | Призначення | Логи |
|--------|-------------|------|
| **trading-bot** | Основний торговий бот | `make logs` |
| **scheduler** | Щоденне тренування моделей о 00:00 UTC | `make logs-scheduler` |
| **telegram-bot** | Інтерактивний Telegram бот для контролю | `make logs-bot` |

---

## 🤖 Telegram Команди

Коли Telegram bot запущений, ви можете відправити:

- `/status` - статус системи
- `/train BTC/USDT` - запустити тренування
- `/models` - список моделей
- `/performance` - результати за 30 днів
- `/lastrun` - деталі останнього тренування
- `/help` - довідка

---

## 🛑 Зупинити все

```bash
make stop
```

---

## 📈 Примеры використання

### Запустити тренування вручну

```bash
make train SYMBOL=ETH/USDT
```

### Дивитися логи в реальному часі

```bash
make logs-all
```

### Перезапустити scheduler

```bash
make restart
```

### Видалити всі дані та контейнери

```bash
make clean
```

---

## 📝 Структура проекту

```
trader/
├── Makefile          ← Use this!
├── start.sh          ← Or this!
├── docker-compose.yml
├── main.py
├── learning/         ← Self-learning module
├── config/
├── strategies/
├── execution/
├── backtesting/
├── monitoring/
├── data/            ← Learning DB, cached data
├── models/          ← Trained models
└── logs/            ← Application logs
```

---

## 💡 Поради

1. **Перша поділка з можливо довгою побудовою образу:**
   ```bash
   make build
   ```

2. **Стежити за логами під час запуску:**
   ```bash
   make logs-all
   ```

3. **Щоб зупинити і видалити все:**
   ```bash
   make clean
   ```

4. **Docker потребує та буде скачувати залежності - це може тривати кілька хвилин.**

