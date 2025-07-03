"""
本地分析器
基于规则和关键词的简单分析器，不依赖外部 API
适合快速测试和离线使用
"""
import os
import sys
import re
from typing import Dict, List, Optional, Any

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.analyzers.base_analyzer import (
    BaseAnalyzer, SentimentResult, KeyPhrasesResult, 
    TopicResult, AnalysisResult
)

class LocalAnalyzer(BaseAnalyzer):
    """本地规则分析器"""
    
    def __init__(self):
        super().__init__()
        
        # 情感分析关键词
        self.positive_keywords = {
            'excellent', 'great', 'awesome', 'perfect', 'love', 'amazing', 
            'fantastic', 'wonderful', 'good', 'nice', 'best', 'recommend',
            'satisfied', 'happy', 'works well', 'stable', 'fast', 'reliable',
            '好', '棒', '不错', '推荐', '满意', '稳定', '快', '可靠'
        }
        
        self.negative_keywords = {
            'terrible', 'awful', 'bad', 'worst', 'hate', 'horrible', 'sucks',
            'broken', 'failed', 'slow', 'unstable', 'problem', 'issue', 
            'bug', 'error', 'crash', 'disconnect', 'poor', 'disappointed',
            '差', '糟糕', '问题', '故障', '慢', '不稳定', '断线', '失望'
        }
        
        # 技术关键词
        self.tech_keywords = {
            'wifi', 'ethernet', 'router', 'access point', 'mesh', 'bandwidth',
            'latency', 'throughput', 'signal', 'coverage', 'firmware', 'setup',
            'configuration', 'network', 'internet', 'connection', 'speed',
            'poe', 'vlan', 'ssid', '无线', '网络', '路由器', '接入点'
        }
        
        # 产品关键词
        self.product_keywords = {
            'omada', 'tp-link', 'tplink', 'archer', 'deco', 'eap', 'oc200',
            'switch', 'gateway', 'controller', 'ubiquiti', 'cisco', 'netgear'
        }
        
        # 主题分类规则
        self.topic_rules = {
            '技术问题': ['problem', 'issue', 'bug', 'error', 'not working', 'broken', '问题', '故障'],
            '产品推荐': ['recommend', 'suggest', 'best', 'which', 'choose', '推荐', '选择'],
            '安装配置': ['setup', 'install', 'configure', 'config', 'how to', '安装', '配置'],
            '性能问题': ['slow', 'speed', 'performance', 'lag', 'latency', '慢', '性能'],
            '购买咨询': ['buy', 'purchase', 'price', 'cost', 'worth', '购买', '价格'],
            '比较评测': ['vs', 'compare', 'better', 'difference', '比较', '对比'],
            '用户体验': ['experience', 'review', 'opinion', 'feedback', '体验', '评价']
        }
        
        self.logger.info("本地分析器初始化完成")
    
    def analyze_sentiment(self, text: str) -> SentimentResult:
        """基于关键词的情感分析"""
        text_lower = text.lower()
        
        positive_count = sum(1 for word in self.positive_keywords if word in text_lower)
        negative_count = sum(1 for word in self.negative_keywords if word in text_lower)
        
        # 计算情感分数
        total_sentiment_words = positive_count + negative_count
        
        if total_sentiment_words == 0:
            sentiment = 'neutral'
            confidence = 0.5
            score = 0.0
        elif positive_count > negative_count:
            sentiment = 'positive'
            confidence = min(0.9, 0.6 + (positive_count - negative_count) * 0.1)
            score = min(1.0, (positive_count - negative_count) / max(total_sentiment_words, 1))
        elif negative_count > positive_count:
            sentiment = 'negative'
            confidence = min(0.9, 0.6 + (negative_count - positive_count) * 0.1)
            score = max(-1.0, -(negative_count - positive_count) / max(total_sentiment_words, 1))
        else:
            sentiment = 'neutral'
            confidence = 0.7
            score = 0.0
        
        return SentimentResult(
            sentiment=sentiment,
            confidence=confidence,
            score=score
        )
    
    def extract_key_phrases(self, text: str) -> KeyPhrasesResult:
        """基于关键词匹配的短语提取"""
        text_lower = text.lower()
        found_phrases = []
        confidence_scores = []
        
        # 检查技术关键词
        for keyword in self.tech_keywords:
            if keyword in text_lower:
                found_phrases.append(keyword)
                confidence_scores.append(0.8)
        
        # 检查产品关键词
        for keyword in self.product_keywords:
            if keyword in text_lower:
                found_phrases.append(keyword)
                confidence_scores.append(0.9)
        
        # 提取数字+单位的模式（如 "100Mbps", "5GHz"）
        tech_patterns = [
            r'\d+\s*(mbps|gbps|mhz|ghz|gb|mb)',
            r'wifi\s*[456]',
            r'802\.11[a-z]+',
            r'ipv[46]'
        ]
        
        for pattern in tech_patterns:
            matches = re.findall(pattern, text_lower)
            for match in matches:
                if isinstance(match, tuple):
                    phrase = ''.join(match)
                else:
                    phrase = match
                found_phrases.append(phrase)
                confidence_scores.append(0.7)
        
        # 去重并限制数量
        unique_phrases = []
        unique_scores = []
        seen = set()
        
        for phrase, score in zip(found_phrases, confidence_scores):
            if phrase not in seen:
                unique_phrases.append(phrase)
                unique_scores.append(score)
                seen.add(phrase)
        
        # 限制到前10个
        if len(unique_phrases) > 10:
            unique_phrases = unique_phrases[:10]
            unique_scores = unique_scores[:10]
        
        return KeyPhrasesResult(
            phrases=unique_phrases,
            confidence_scores=unique_scores
        )
    
    def classify_topic(self, text: str) -> TopicResult:
        """基于规则的主题分类"""
        text_lower = text.lower()
        topic_scores = {}
        
        # 检查每个主题的关键词
        for topic, keywords in self.topic_rules.items():
            score = 0
            matched_keywords = 0
            
            for keyword in keywords:
                if keyword in text_lower:
                    score += 1
                    matched_keywords += 1
            
            if score > 0:
                # 归一化分数
                confidence = min(0.9, 0.3 + matched_keywords * 0.2)
                topic_scores[topic] = confidence
        
        # 排序并选择前3个主题
        sorted_topics = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)[:3]
        
        if not sorted_topics:
            return TopicResult(topics=['其他'], confidence_scores=[0.5])
        
        topics = [topic for topic, _ in sorted_topics]
        scores = [score for _, score in sorted_topics]
        
        return TopicResult(
            topics=topics,
            confidence_scores=scores
        )
    
    def _generate_summary(self, text: str) -> Optional[str]:
        """生成简单摘要"""
        if len(text) <= 50:
            return text
        
        # 简单的摘要：取前50个字符
        sentences = text.split('.')
        if sentences and len(sentences[0]) <= 100:
            return sentences[0].strip()
        
        return text[:50] + "..."
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            # 测试各个功能
            test_text = "This router is great but has some connection issues"
            
            sentiment = self.analyze_sentiment(test_text)
            phrases = self.extract_key_phrases(test_text)
            topics = self.classify_topic(test_text)
            
            return {
                "status": "healthy",
                "analyzer": "Local",
                "test_results": {
                    "sentiment": sentiment.sentiment,
                    "phrases_count": len(phrases.phrases),
                    "topics_count": len(topics.topics)
                },
                "keywords_loaded": {
                    "positive": len(self.positive_keywords),
                    "negative": len(self.negative_keywords),
                    "tech": len(self.tech_keywords),
                    "product": len(self.product_keywords)
                }
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "analyzer": "Local",
                "error": str(e)
            } 