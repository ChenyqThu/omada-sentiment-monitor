"""
AI 分析器基础接口
定义统一的分析接口，支持多种 AI 服务
"""
import os
import sys
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.utils.logger import LoggerMixin

@dataclass
class SentimentResult:
    """情感分析结果"""
    sentiment: str  # positive, negative, neutral
    confidence: float  # 0.0 - 1.0
    score: float  # -1.0 到 1.0，负数表示负面，正数表示正面

@dataclass
class KeyPhrasesResult:
    """关键短语提取结果"""
    phrases: List[str]
    confidence_scores: List[float]

@dataclass
class TopicResult:
    """主题分类结果"""
    topics: List[str]
    confidence_scores: List[float]

@dataclass
class AnalysisResult:
    """完整分析结果"""
    text: str
    sentiment: Optional[SentimentResult] = None
    key_phrases: Optional[KeyPhrasesResult] = None
    topics: Optional[TopicResult] = None
    summary: Optional[str] = None
    processing_time: Optional[float] = None
    error: Optional[str] = None

class BaseAnalyzer(ABC, LoggerMixin):
    """AI 分析器基础类"""
    
    def __init__(self):
        super().__init__()
        self.analyzer_name = self.__class__.__name__
    
    @abstractmethod
    def analyze_sentiment(self, text: str) -> SentimentResult:
        """分析文本情感"""
        pass
    
    @abstractmethod
    def extract_key_phrases(self, text: str) -> KeyPhrasesResult:
        """提取关键短语"""
        pass
    
    @abstractmethod
    def classify_topic(self, text: str) -> TopicResult:
        """主题分类"""
        pass
    
    def analyze_comprehensive(self, text: str, 
                            enable_sentiment: bool = True,
                            enable_key_phrases: bool = True,
                            enable_topic: bool = True) -> AnalysisResult:
        """综合分析"""
        start_time = datetime.now()
        result = AnalysisResult(text=text)
        
        try:
            if enable_sentiment:
                result.sentiment = self.analyze_sentiment(text)
            
            if enable_key_phrases:
                result.key_phrases = self.extract_key_phrases(text)
            
            if enable_topic:
                result.topics = self.classify_topic(text)
            
            # 生成摘要（可选）
            result.summary = self._generate_summary(text)
            
        except Exception as e:
            self.logger.error(f"分析失败: {e}")
            result.error = str(e)
        
        result.processing_time = (datetime.now() - start_time).total_seconds()
        return result
    
    def analyze_batch(self, texts: List[str], **kwargs) -> List[AnalysisResult]:
        """批量分析"""
        results = []
        for text in texts:
            result = self.analyze_comprehensive(text, **kwargs)
            results.append(result)
        return results
    
    def _generate_summary(self, text: str) -> Optional[str]:
        """生成文本摘要（子类可重写）"""
        if len(text) <= 100:
            return text
        return text[:100] + "..."
    
    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        pass 