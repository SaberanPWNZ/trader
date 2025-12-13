"""
Data caching implementation.
"""
import time
from typing import Any, Optional, Dict
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class CacheEntry:
    """Single cache entry with expiration."""
    value: Any
    expires_at: float
    
    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() > self.expires_at


class DataCache:
    """
    Simple in-memory cache with TTL support.
    
    Thread-safe implementation for caching market data
    to reduce API calls and improve performance.
    """
    
    def __init__(self, default_ttl: int = 60):
        """
        Initialize cache.
        
        Args:
            default_ttl: Default time-to-live in seconds
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = Lock()
        self._default_ttl = default_ttl
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                return None
            
            if entry.is_expired:
                del self._cache[key]
                return None
            
            return entry.value
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default if not specified)
        """
        ttl = ttl or self._default_ttl
        expires_at = time.time() + ttl
        
        with self._lock:
            self._cache[key] = CacheEntry(value=value, expires_at=expires_at)
    
    def delete(self, key: str) -> bool:
        """
        Delete entry from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if entry was deleted, False if not found
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.
        
        Returns:
            Number of entries removed
        """
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired
            ]
            
            for key in expired_keys:
                del self._cache[key]
            
            return len(expired_keys)
    
    @property
    def size(self) -> int:
        """Get number of entries in cache."""
        with self._lock:
            return len(self._cache)
    
    def get_or_set(self, key: str, factory, ttl: Optional[int] = None) -> Any:
        """
        Get value from cache or compute and cache it.
        
        Args:
            key: Cache key
            factory: Callable to compute value if not cached
            ttl: Time-to-live in seconds
            
        Returns:
            Cached or computed value
        """
        value = self.get(key)
        
        if value is None:
            value = factory()
            self.set(key, value, ttl)
        
        return value
