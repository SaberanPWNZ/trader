"""
Tests for risk management.
"""
import pytest
from datetime import datetime, timedelta
from risk.manager import RiskManager, RiskState
from risk.position_sizer import PositionSizer
from risk.kill_switch import KillSwitch
from data.models import Position, Signal
from config.constants import SignalType


@pytest.fixture
def risk_manager():
    """Create a risk manager instance."""
    return RiskManager(initial_balance=10000.0)


@pytest.fixture
def position_sizer():
    """Create a position sizer instance."""
    return PositionSizer()


@pytest.fixture
def kill_switch():
    """Create a kill switch instance."""
    return KillSwitch()


class TestRiskManager:
    """Test cases for RiskManager class."""
    
    def test_initialization(self, risk_manager):
        """Test risk manager initialization."""
        assert risk_manager.state.current_balance == 10000.0
        assert risk_manager.state.peak_balance == 10000.0
        assert risk_manager.state.daily_pnl == 0.0
        assert not risk_manager.state.kill_switch_active
    
    def test_can_trade_normal(self, risk_manager):
        """Test can_trade under normal conditions."""
        can_trade, reason = risk_manager.can_trade("BTC/USDT")
        assert can_trade
        assert reason == "OK"
    
    def test_can_trade_kill_switch_active(self, risk_manager):
        """Test can_trade when kill switch is active."""
        risk_manager.state.kill_switch_active = True
        can_trade, reason = risk_manager.can_trade("BTC/USDT")
        assert not can_trade
        assert "Kill switch" in reason
    
    def test_can_trade_existing_position(self, risk_manager):
        """Test can_trade with existing position."""
        position = Position(
            id="test",
            symbol="BTC/USDT",
            side="long",
            entry_price=50000,
            current_price=50000,
            amount=0.1,
            unrealized_pnl=0,
            realized_pnl=0
        )
        risk_manager.state.open_positions["BTC/USDT"] = position
        
        can_trade, reason = risk_manager.can_trade("BTC/USDT")
        assert not can_trade
        assert "already open" in reason.lower()
    
    def test_calculate_position_size(self, risk_manager):
        """Test position size calculation."""
        entry_price = 50000
        stop_loss = 49000  # 2% risk
        
        position_size = risk_manager.calculate_position_size(
            entry_price, stop_loss, "BTC/USDT"
        )
        
        # With 2% risk and $1000 price difference
        # Account risk = 10000 * 0.02 = 200
        # Position size = 200 / 1000 = 0.2
        assert position_size > 0
        assert position_size <= 10000 * 0.30 / entry_price  # Max position size
    
    def test_close_position_updates_balance(self, risk_manager):
        """Test that closing position updates balance correctly."""
        initial_balance = risk_manager.state.current_balance
        
        risk_manager.close_position("BTC/USDT", 500.0)  # Profit
        
        assert risk_manager.state.current_balance == initial_balance + 500.0
        assert risk_manager.state.daily_pnl == 500.0
    
    def test_consecutive_losses_trigger_cooldown(self, risk_manager):
        """Test that consecutive losses trigger cooldown."""
        # Simulate consecutive losses
        for _ in range(risk_manager.config.max_consecutive_losses):
            risk_manager.close_position("BTC/USDT", -100.0)
        
        assert risk_manager.state.cooldown_until is not None
    
    def test_check_stop_loss_long(self, risk_manager):
        """Test stop loss check for long position."""
        position = Position(
            id="test",
            symbol="BTC/USDT",
            side="long",
            entry_price=50000,
            current_price=49000,
            amount=0.1,
            unrealized_pnl=-100,
            realized_pnl=0,
            stop_loss=49500
        )
        
        assert risk_manager.check_stop_loss(position, 49400)  # Below stop
        assert not risk_manager.check_stop_loss(position, 49600)  # Above stop


class TestPositionSizer:
    """Test cases for PositionSizer class."""
    
    def test_fixed_risk(self, position_sizer):
        """Test fixed risk position sizing."""
        position_size = position_sizer.fixed_risk(
            account_balance=10000,
            entry_price=50000,
            stop_loss=49000,
            risk_percent=0.02
        )
        
        # Risk amount = 10000 * 0.02 = 200
        # Price risk = 50000 - 49000 = 1000
        # Position size = 200 / 1000 = 0.2
        assert abs(position_size - 0.2) < 0.01
    
    def test_volatility_adjusted(self, position_sizer):
        """Test volatility-adjusted position sizing."""
        position_size = position_sizer.volatility_adjusted(
            account_balance=10000,
            entry_price=50000,
            atr=500,
            atr_multiplier=2.0,
            risk_percent=0.02
        )
        
        # Stop distance = 500 * 2 = 1000
        # Should be same as fixed_risk with SL at 49000
        assert position_size > 0


class TestKillSwitch:
    """Test cases for KillSwitch class."""
    
    def test_activation(self, kill_switch):
        """Test kill switch activation."""
        assert not kill_switch.is_active
        
        kill_switch.activate("Test reason")
        
        assert kill_switch.is_active
        assert kill_switch.activation_reason == "Test reason"
        assert kill_switch.activation_time is not None
    
    def test_deactivation_requires_confirmation(self, kill_switch):
        """Test that deactivation requires confirmation."""
        kill_switch.activate("Test")
        
        # Wrong confirmation
        result = kill_switch.deactivate("wrong")
        assert not result
        assert kill_switch.is_active
        
        # Correct confirmation
        result = kill_switch.deactivate("CONFIRM_DEACTIVATE")
        assert result
        assert not kill_switch.is_active
    
    def test_check_drawdown(self, kill_switch):
        """Test drawdown check."""
        # Below limit
        assert not kill_switch.check_drawdown(0.05)
        assert not kill_switch.is_active
        
        # Above limit
        kill_switch.is_active = False  # Reset
        assert kill_switch.check_drawdown(0.15)
        assert kill_switch.is_active
