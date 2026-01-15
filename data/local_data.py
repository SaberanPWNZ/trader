"""
Local data management for development mode.

Handles loading, saving, and processing local OHLCV data.
"""
import pandas as pd
from pathlib import Path
from typing import Optional, Dict
from loguru import logger

from config.settings import settings
from data.mock_generator import MockDataGenerator


class LocalDataManager:
    """Manage local data files for development."""
    
    def __init__(self):
        """Initialize local data manager."""
        self.data_dir = Path(settings.dev.local_data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"LocalDataManager initialized (dir: {self.data_dir})")
    
    def get_cached_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str
    ) -> Optional[pd.DataFrame]:
        """
        Load data from local cache if available.
        
        Args:
            symbol: Trading symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            
        Returns:
            DataFrame or None if not cached
        """
        filename = f"{symbol}_{start_date}_{end_date}.csv"
        filepath = self.data_dir / filename
        
        if filepath.exists():
            try:
                df = pd.read_csv(filepath, index_col='timestamp', parse_dates=True)
                logger.info(f"✅ Loaded cached data from {filepath}")
                return df
            except Exception as e:
                logger.warning(f"Failed to load cached data: {e}")
                return None
        
        return None
    
    def save_data(
        self,
        df: pd.DataFrame,
        symbol: str,
        start_date: str,
        end_date: str
    ) -> str:
        """
        Save data to local cache.
        
        Args:
            df: DataFrame with OHLCV data
            symbol: Trading symbol
            start_date: Start date
            end_date: End date
            
        Returns:
            Path to saved file
        """
        filename = f"{symbol}_{start_date}_{end_date}.csv"
        filepath = self.data_dir / filename
        
        df.to_csv(filepath)
        logger.info(f"💾 Saved data to {filepath}")
        
        return str(filepath)
    
    def generate_and_cache(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        force_regenerate: bool = False
    ) -> pd.DataFrame:
        """
        Generate mock data and cache it locally.
        
        Args:
            symbol: Trading symbol
            start_date: Start date
            end_date: End date
            force_regenerate: Force regenerate even if cached
            
        Returns:
            DataFrame with OHLCV data
        """
        # Try to load from cache first
        if not force_regenerate:
            cached = self.get_cached_data(symbol, start_date, end_date)
            if cached is not None:
                return cached
        
        # Generate new data
        logger.info(f"📊 Generating mock data for {symbol}")
        generator = MockDataGenerator()
        df = generator.generate_ohlcv(symbol, start_date, end_date)
        
        # Save to cache
        self.save_data(df, symbol, start_date, end_date)
        
        return df
    
    def list_cached_files(self) -> list:
        """
        List all cached data files.
        
        Returns:
            List of cached file paths
        """
        files = list(self.data_dir.glob("*.csv"))
        logger.info(f"Found {len(files)} cached data files")
        return files
    
    def clear_cache(self, symbol: Optional[str] = None) -> int:
        """
        Clear cached data files.
        
        Args:
            symbol: Clear specific symbol, or None for all
            
        Returns:
            Number of files deleted
        """
        if symbol:
            files = list(self.data_dir.glob(f"{symbol}_*.csv"))
        else:
            files = list(self.data_dir.glob("*.csv"))
        
        deleted = 0
        for f in files:
            try:
                f.unlink()
                deleted += 1
            except Exception as e:
                logger.warning(f"Failed to delete {f}: {e}")
        
        logger.info(f"🗑️ Deleted {deleted} cached files")
        return deleted
    
    def get_data_summary(self) -> Dict:
        """
        Get summary of cached data.
        
        Returns:
            Dict with data statistics
        """
        files = self.list_cached_files()
        
        summary = {
            'total_files': len(files),
            'files': [],
            'total_size_mb': 0.0
        }
        
        for f in files:
            try:
                size_mb = f.stat().st_size / (1024 * 1024)
                summary['total_size_mb'] += size_mb
                summary['files'].append({
                    'name': f.name,
                    'size_mb': round(size_mb, 2)
                })
            except Exception as e:
                logger.warning(f"Failed to get stats for {f}: {e}")
        
        return summary
    
    @staticmethod
    def merge_data(dataframes: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        Merge multiple symbol dataframes.
        
        Args:
            dataframes: Dict of symbol: DataFrame
            
        Returns:
            Merged DataFrame
        """
        merged = pd.concat(dataframes, axis=1)
        logger.info(f"✅ Merged {len(dataframes)} dataframes")
        return merged


class DataLoader:
    """High-level data loading interface for dev mode."""
    
    def __init__(self):
        """Initialize data loader."""
        self.manager = LocalDataManager()
        self.generator = MockDataGenerator()
    
    def load_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Load data, using cache if available.
        
        Args:
            symbol: Symbol
            start_date: Start date
            end_date: End date
            use_cache: Use cached data if available
            
        Returns:
            DataFrame with OHLCV data
        """
        if settings.dev.use_mock_data:
            if use_cache:
                return self.manager.generate_and_cache(symbol, start_date, end_date)
            else:
                logger.info(f"📊 Generating fresh mock data (cache disabled)")
                return self.generator.generate_ohlcv(symbol, start_date, end_date)
        else:
            # In production mode, would load from real API
            logger.error("Dev mode disabled, cannot use mock data")
            raise RuntimeError("Dev mode not enabled")
    
    def load_multiple(
        self,
        symbols: list,
        start_date: str,
        end_date: str
    ) -> Dict[str, pd.DataFrame]:
        """
        Load data for multiple symbols.
        
        Args:
            symbols: List of symbols
            start_date: Start date
            end_date: End date
            
        Returns:
            Dict of symbol: DataFrame
        """
        data = {}
        for symbol in symbols:
            data[symbol] = self.load_data(symbol, start_date, end_date)
        
        return data
