"""
OpenAI 分析器
使用 OpenAI API 进行情感分析和内容分析
支持第三方 API 服务（通过 base_url 配置）
"""
import os
import sys
import json
import time
from typing import Dict, List, Optional, Any

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.settings import openai_config, ai_analysis_config
from src.analyzers.base_analyzer import (
    BaseAnalyzer, SentimentResult, KeyPhrasesResult, 
    TopicResult, AnalysisResult
)

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

class OpenAIAnalyzer(BaseAnalyzer):
    """OpenAI 分析器"""
    
    def __init__(self):
        super().__init__()
        
        if OpenAI is None:
            raise ImportError("请安装 openai 库: pip install openai")
        
        # 初始化 OpenAI 客户端，支持自定义 base_url
        client_kwargs = {
            'api_key': openai_config.api_key
        }
        
        # 只有当 base_url 不是默认值时才设置
        if openai_config.base_url != 'https://api.openai.com/v1':
            client_kwargs['base_url'] = openai_config.base_url
        
        self.client = OpenAI(**client_kwargs)
        
        self.model = openai_config.model
        self.max_tokens = openai_config.max_tokens
        self.temperature = openai_config.temperature
        
        self.logger.info(f"OpenAI 分析器初始化完成")
        self.logger.info(f"API 端点: {openai_config.base_url}")
        self.logger.info(f"使用模型: {self.model}")
    
    def _call_openai(self, messages: List[Dict], max_tokens: Optional[int] = None) -> str:
        """调用 OpenAI API"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens or self.max_tokens,
                temperature=self.temperature,
                timeout=openai_config.timeout
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            self.logger.error(f"OpenAI API 调用失败: {e}")
            raise
    
    def analyze_sentiment(self, text: str) -> SentimentResult:
        """分析文本情感"""
        prompt = f"""
请分析以下文本的情感倾向，并返回JSON格式的结果：

文本: "{text}"

请返回以下格式的JSON：
{{
    "sentiment": "positive/negative/neutral",
    "confidence": 0.0-1.0之间的数值,
    "score": -1.0到1.0之间的数值（负数表示负面，正数表示正面）,
    "reasoning": "简短的分析理由"
}}

注意：
- positive: 正面情感（推荐、满意、赞扬等）
- negative: 负面情感（抱怨、不满、批评等）  
- neutral: 中性情感（陈述事实、询问等）
"""
        
        messages = [
            {"role": "system", "content": "你是一个专业的情感分析专家，擅长分析技术产品相关的用户反馈。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = self._call_openai(messages, max_tokens=200)
            
            # 解析 JSON 响应
            result_data = json.loads(response)
            
            return SentimentResult(
                sentiment=result_data.get('sentiment', 'neutral'),
                confidence=float(result_data.get('confidence', 0.5)),
                score=float(result_data.get('score', 0.0))
            )
            
        except json.JSONDecodeError as e:
            self.logger.warning(f"JSON 解析失败，使用默认值: {e}")
            return SentimentResult(sentiment='neutral', confidence=0.5, score=0.0)
        except Exception as e:
            self.logger.error(f"情感分析失败: {e}")
            return SentimentResult(sentiment='neutral', confidence=0.0, score=0.0)
    
    def extract_key_phrases(self, text: str) -> KeyPhrasesResult:
        """提取关键短语"""
        prompt = f"""
请从以下文本中提取关键短语，重点关注产品名称、技术术语、问题描述等：

文本: "{text}"

请返回JSON格式：
{{
    "phrases": ["关键短语1", "关键短语2", ...],
    "confidence_scores": [0.9, 0.8, ...]
}}

要求：
- 提取5-10个最重要的关键短语
- 优先提取产品名称、技术问题、用户需求
- confidence_scores 表示每个短语的重要性（0.0-1.0）
"""
        
        messages = [
            {"role": "system", "content": "你是一个专业的文本分析专家，擅长从技术讨论中提取关键信息。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = self._call_openai(messages, max_tokens=300)
            result_data = json.loads(response)
            
            phrases = result_data.get('phrases', [])
            confidence_scores = result_data.get('confidence_scores', [0.5] * len(phrases))
            
            # 确保长度一致
            if len(confidence_scores) != len(phrases):
                confidence_scores = [0.5] * len(phrases)
            
            return KeyPhrasesResult(
                phrases=phrases,
                confidence_scores=confidence_scores
            )
            
        except Exception as e:
            self.logger.error(f"关键短语提取失败: {e}")
            return KeyPhrasesResult(phrases=[], confidence_scores=[])
    
    def classify_topic(self, text: str) -> TopicResult:
        """主题分类"""
        prompt = f"""
请对以下文本进行主题分类，重点关注网络设备和技术问题：

文本: "{text}"

请返回JSON格式：
{{
    "topics": ["主题1", "主题2", ...],
    "confidence_scores": [0.9, 0.8, ...]
}}

可能的主题包括但不限于：
- 产品推荐
- 技术问题
- 安装配置
- 性能问题
- 比较评测
- 购买咨询
- 故障排除
- 网络设计
- 价格讨论
- 用户体验

要求：
- 选择最相关的1-3个主题
- confidence_scores 表示匹配度（0.0-1.0）
"""
        
        messages = [
            {"role": "system", "content": "你是一个专业的主题分类专家，擅长分析网络设备相关的讨论内容。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = self._call_openai(messages, max_tokens=200)
            result_data = json.loads(response)
            
            topics = result_data.get('topics', [])
            confidence_scores = result_data.get('confidence_scores', [0.5] * len(topics))
            
            # 确保长度一致
            if len(confidence_scores) != len(topics):
                confidence_scores = [0.5] * len(topics)
            
            return TopicResult(
                topics=topics,
                confidence_scores=confidence_scores
            )
            
        except Exception as e:
            self.logger.error(f"主题分类失败: {e}")
            return TopicResult(topics=[], confidence_scores=[])
    
    def _generate_summary(self, text: str) -> Optional[str]:
        """生成文本摘要"""
        if len(text) <= 100:
            return text
        
        prompt = f"""
请为以下文本生成一个简洁的摘要（不超过50字）：

文本: "{text}"

要求：
- 保留关键信息
- 突出主要问题或观点
- 简洁明了
"""
        
        messages = [
            {"role": "system", "content": "你是一个专业的文本摘要专家。"},
            {"role": "user", "content": prompt}
        ]
        
        try:
            return self._call_openai(messages, max_tokens=100)
        except Exception as e:
            self.logger.error(f"摘要生成失败: {e}")
            return text[:50] + "..."
    
    def analyze_batch(self, texts: List[str], **kwargs) -> List[AnalysisResult]:
        """批量分析（优化版本）"""
        results = []
        batch_size = ai_analysis_config.batch_size
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            self.logger.info(f"处理批次 {i//batch_size + 1}/{(len(texts)-1)//batch_size + 1}")
            
            for text in batch:
                result = self.analyze_comprehensive(text, **kwargs)
                results.append(result)
                
                # 避免 API 限流
                time.sleep(0.1)
        
        return results
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            test_response = self._call_openai([
                {"role": "user", "content": "Hello, this is a health check."}
            ], max_tokens=10)
            
            return {
                "status": "healthy",
                "analyzer": "OpenAI",
                "model": self.model,
                "base_url": openai_config.base_url,
                "test_response": test_response[:50] + "..." if len(test_response) > 50 else test_response
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "analyzer": "OpenAI", 
                "error": str(e),
                "model": self.model,
                "base_url": openai_config.base_url
            } 