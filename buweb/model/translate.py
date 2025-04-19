import sys, os
import asyncio
import json
import logging
import time
from typing import TypedDict
from googletrans import Translator

class TransEntry(TypedDict):
    txt: str # translated text
    tm: float # access time
    sz:int # estimated size

class Translate:
    # Maximum cache size (10MB)
    MAX_CACHE_SIZE = 10 * 1024 * 1024  # 10MB in bytes
    # Estimated JSON overhead (additional bytes per key/value)
    JSON_OVERHEAD_PER_ENTRY = 10 # Overhead for quotes, colons, commas, etc.

    def __init__(self, lang, cachefile: str | None = None):
        self.lang = lang
        self._cache: dict[str, TransEntry] = {}  # {text: {"translation": translated_text, "tm": access_time}}
        self.cachefile = cachefile
        self._current_size = 0 # Current cache size (estimated)
        
        # Configuring the logger
        self.logger = logging.getLogger(__name__)
        
        # If a cache file is specified, try to read it
        if self.cachefile:
            try:
                if os.path.exists(self.cachefile):
                    with open(self.cachefile, 'r', encoding='utf-8') as f:
                        loaded_cache = json.load(f)
                        self._cache = loaded_cache
                        # Estimate the size of the cache read
                        self._calculate_cache_size()
                        self.logger.info(f"Loaded cache from {self.cachefile}, estimated size: {self._current_size} bytes")
            except Exception as e:
                self.logger.error(f"Failed to load cache from {self.cachefile}: {str(e)}")
                # Processing continues even if loading fails (operates with memory cache only)

    def _calculate_cache_size(self):
        """Estimate cache size"""
        self._current_size = 0
        for key, entry in self._cache.items():
            # Size of key + size of translation text + size of timestamp (assumed fixed 10 bytes) + JSON overhead
            entry_size = entry["sz"]
            self._current_size += entry_size

    def _estimate_entry_size(self, key, translation):
        """Estimate the size of the entries"""
        return len(key.encode('utf-8')) + len(translation.encode('utf-8')) + 10 + self.JSON_OVERHEAD_PER_ENTRY

    async def translate(self, from_text):
        current_time = time.time()
        
        # If it is in the cache, update the timestamp and return it.
        if from_text in self._cache:
            cache_entry = self._cache[from_text]
            cache_entry["tm"] = current_time # Update access time
            return cache_entry["txt"]
        
        # Execute the translation
        translator = Translator()
        result = await translator.translate(from_text, dest=self.lang)
        to_text = result.text
        
        # Estimate the size of the new entry
        new_entry_size = self._estimate_entry_size(from_text, to_text)
        
        # Check cache size and remove old entries if necessary
        if self._current_size + new_entry_size > self.MAX_CACHE_SIZE:
            self._trim_cache(new_entry_size)
        
        # Add to cache
        self._cache[from_text] = TransEntry( txt=to_text, tm=current_time, sz=new_entry_size )
        self._current_size += new_entry_size
        
        # If a cache file is specified, try to save it
        if self.cachefile:
            try:
                with open(self.cachefile, 'w', encoding='utf-8') as f:
                    json.dump(self._cache, f, ensure_ascii=False, indent=2)
            except Exception as e:
                self.logger.error(f"Failed to save cache to {self.cachefile}: {str(e)}")
                # Processing continues even if saving fails
        
        return to_text
    
    def _trim_cache(self, needed_space):
        """Remove old entries from the cache to free up the specified amount of space"""
        if needed_space > self.MAX_CACHE_SIZE:
            # If the required space exceeds the maximum cache size, clear the entire cache
            self.logger.warning(f"Required space ({needed_space} bytes) exceeds maximum cache size. Clearing all cache.")
            self._cache.clear()
            self._current_size = 0
            return
        
        self.logger.info(f"Trimming cache to make room for {needed_space} bytes")
        
        # List of entries sorted by timestamp (oldest first)
        sorted_entries = sorted(self._cache.items(), key=lambda x: x[1]["tm"])
        
        # Delete old entries until enough space is available
        freed_space = 0
        removed_count = 0
        
        while freed_space < needed_space and sorted_entries:
            oldest_key, oldest_entry = sorted_entries.pop(0)
            entry_size = oldest_entry["sz"]
            del self._cache[oldest_key]
            
            freed_space += entry_size
            self._current_size -= entry_size
            removed_count += 1
        
        self.logger.debug(f"Removed {removed_count} old cache entries. Freed {freed_space} bytes.")
