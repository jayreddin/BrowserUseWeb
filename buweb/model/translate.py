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
    # 最大キャッシュサイズ（10MB）
    MAX_CACHE_SIZE = 10 * 1024 * 1024  # 10MB in bytes
    # JSONのオーバーヘッド概算（キー・値ごとの追加バイト数）
    JSON_OVERHEAD_PER_ENTRY = 10  # 引用符、コロン、カンマなどのオーバーヘッド

    def __init__(self, lang, cachefile: str | None = None):
        self.lang = lang
        self._cache: dict[str, TransEntry] = {}  # {text: {"translation": translated_text, "tm": access_time}}
        self.cachefile = cachefile
        self._current_size = 0  # 現在のキャッシュサイズ（概算）
        
        # ロガーの設定
        self.logger = logging.getLogger(__name__)
        
        # キャッシュファイルが指定されている場合、読み込みを試みる
        if self.cachefile:
            try:
                if os.path.exists(self.cachefile):
                    with open(self.cachefile, 'r', encoding='utf-8') as f:
                        loaded_cache = json.load(f)
                        self._cache = loaded_cache
                        # 読み込んだキャッシュのサイズを概算
                        self._calculate_cache_size()
                        self.logger.info(f"Loaded cache from {self.cachefile}, estimated size: {self._current_size} bytes")
            except Exception as e:
                self.logger.error(f"Failed to load cache from {self.cachefile}: {str(e)}")
                # 読み込みに失敗しても処理は継続（メモリキャッシュのみで動作）

    def _calculate_cache_size(self):
        """キャッシュサイズを概算で計算"""
        self._current_size = 0
        for key, entry in self._cache.items():
            # キーのサイズ + 翻訳テキストのサイズ + タイムスタンプのサイズ（固定で10バイトと仮定） + JSONオーバーヘッド
            entry_size = entry["sz"]
            self._current_size += entry_size

    def _estimate_entry_size(self, key, translation):
        """エントリのサイズを概算"""
        return len(key.encode('utf-8')) + len(translation.encode('utf-8')) + 10 + self.JSON_OVERHEAD_PER_ENTRY

    async def translate(self, from_text):
        current_time = time.time()
        
        # キャッシュにある場合は、タイムスタンプを更新して返す
        if from_text in self._cache:
            cache_entry = self._cache[from_text]
            cache_entry["tm"] = current_time  # アクセス時間を更新
            return cache_entry["txt"]
        
        # 翻訳を実行
        translator = Translator()
        result = await translator.translate(from_text, dest=self.lang)
        to_text = result.text
        
        # 新しいエントリのサイズを概算
        new_entry_size = self._estimate_entry_size(from_text, to_text)
        
        # キャッシュサイズをチェックし、必要に応じて古いエントリを削除
        if self._current_size + new_entry_size > self.MAX_CACHE_SIZE:
            self._trim_cache(new_entry_size)
        
        # キャッシュに追加
        self._cache[from_text] = TransEntry( txt=to_text, tm=current_time, sz=new_entry_size )
        self._current_size += new_entry_size
        
        # キャッシュファイルが指定されている場合、保存を試みる
        if self.cachefile:
            try:
                with open(self.cachefile, 'w', encoding='utf-8') as f:
                    json.dump(self._cache, f, ensure_ascii=False, indent=2)
            except Exception as e:
                self.logger.error(f"Failed to save cache to {self.cachefile}: {str(e)}")
                # 保存に失敗しても処理は継続
        
        return to_text
    
    def _trim_cache(self, needed_space):
        """キャッシュから古いエントリを削除して、指定された容量を確保する"""
        if needed_space > self.MAX_CACHE_SIZE:
            # 必要なスペースが最大キャッシュサイズを超える場合は、キャッシュを全てクリア
            self.logger.warning(f"Required space ({needed_space} bytes) exceeds maximum cache size. Clearing all cache.")
            self._cache.clear()
            self._current_size = 0
            return
        
        self.logger.info(f"Trimming cache to make room for {needed_space} bytes")
        
        # タイムスタンプでソートしたエントリのリスト（古い順）
        sorted_entries = sorted(self._cache.items(), key=lambda x: x[1]["tm"])
        
        # 必要なスペースが確保できるまで、古いエントリから削除
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
